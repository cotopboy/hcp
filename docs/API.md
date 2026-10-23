# HCP HTTP API

控制器在局域网内提供一个 JSON HTTP 接口（默认端口 `8080`，无认证——只应在家庭局域网中使用，不要在路由器上做端口映射）。iPhone App 和 [`scripts/hcpctl.sh`](../scripts/hcpctl.sh) 都只用这个接口。

- 编码：UTF‑8 JSON；请求体是 JSON 对象，最大 4 KB
- 出错时返回 `{"error": "说明"}` 和对应状态码：`400` 参数错误，`404` 路径不存在，`405` 方法不对，`409` 当前状态不允许（例如非手动模式下移动阀门、过热保护中开大阀门），`500` 内部错误
- Bonjour：服务类型 `_hcp._tcp`，由 avahi 广播（[deploy/hcp-avahi.service](../deploy/hcp-avahi.service)）

## GET /api/health

```json
{"ok": true, "version": "2.0.0"}
```

## GET /api/status

完整状态，App 每 3 秒轮询一次。

```json
{
  "time": 1792742048.67,
  "uptime_seconds": 20,
  "mode": "auto",
  "phase": "normal",
  "busy": null,
  "target_temperature": 50,
  "target_range": {"min": 30, "max": 75, "upper_band": 10},
  "temperatures": {
    "mainInlet":    {"value": 74.98, "ok": true, "updated_at": 1792742038.77, "error": null},
    "mainReturn":   {"value": 55.98, "ok": true, "updated_at": 1792742038.77, "error": null},
    "heatingInlet": {"value": 34.16, "ok": true, "updated_at": 1792742038.77, "error": null},
    "heatingReturn":{"value": 29.74, "ok": true, "updated_at": 1792742038.77, "error": null},
    "waterInlet":   {"value": 44.94, "ok": true, "updated_at": 1792742038.77, "error": null}
  },
  "valve": {
    "position": 9, "min": -25, "max": 95, "percent": 9,
    "absolute": 34, "zero_offset": 25, "full_stroke": 120,
    "auto_min": 10, "auto_max": 41, "reduced": 0,
    "manual_target": null, "moving": null, "calibrated": true
  },
  "last_decision": {"op": "hold", "rule": "in_range", "reason": "within target range",
                    "moved": false, "at_limit": false, "at": 1792742047.84},
  "zero_calibration": null,
  "water_tank": null,
  "night_saver": {"enabled": true, "active": false, "start": "00:30", "end": "06:30"},
  "alarms": []
}
```

| 字段 | 取值 |
|---|---|
| `mode` | `off` 关闭 / `auto` 自动 / `manual` 手动 |
| `phase` | `zero_calibration`（正在设置零点，控制暂停）、`idle`（关闭）、`night_saver`（夜间节能时段内，暖气关闭）、`manual`、`normal`（自动调节）、`water_tank`（热水箱加热：热水控制器把阀门开满，本控制器在任何模式下都不动阀门）、`no_consumption`（无热量消耗，阀门在低开度）、`overheat`（过热保护）、`sensor_fault`（必需传感器无读数，阀门保持不动）、`relay_fault`（继电器写入失败） |
| `busy` | 正在执行的长动作：`calibrating`、`closing`、`opening to ready position`、`overheat protection`，否则 `null` |
| `temperatures.*.value` | °C；传感器故障或读数超过 60 秒未更新时为 `null` |
| `valve.position` | 开度，单位「步」（继电器通电 0.5 秒），相对零点（刚有水流通过的位置）；范围 `min`（= −`zero_offset`，完全关闭）到 `max` |
| `valve.absolute` | 离完全关闭（机械限位）的步数，0..`full_stroke` |
| `valve.zero_offset` | 零点离完全关闭的步数 |
| `zero_calibration` | 设置零点进行中时为 `{"stage": "closing"\|"ready", "absolute", "target", "max_offset", "max_jog"}`，否则 `null`。`target` = 当前位置加上还没走完的点动 |
| `water_tank` | 热水箱加热中为 `{"started_at", "min_minutes", "timeout_minutes"}`（`started_at` 是 Unix 时间），否则 `null`。期间 `valve.calibrated` 为 `false`（位置未知），手动移动、重新计数、设置零点返回 `409`；切换模式会被接受，加热结束后生效 |
| `night_saver` | `enabled`：是否开启；`active`：现在处于节能时段（开启且在 `start`–`end` 之间，树莓派本地时间）。`active` 时自动 / 手动模式像关闭一样把阀门关到零点，`mode` 不变；时段结束后恢复（手动模式回到之前的位置）。期间手动移动返回 `409` |
| `valve.moving` | `up` / `down` / `null` |
| `last_decision.rule` | `heating_inlet_low`、`sum_low`、`below_target`、`sum_high`、`above_target`、`in_range`（见 [ARCHITECTURE.md](ARCHITECTURE.md#5-自动控制)） |
| `alarms[].code` | `relay_fault`、`overheat`、`no_consumption`、`water_tank`、`sensor_fault`（带 `sensor` 字段）、`uncalibrated`（热水箱加热期间不报） |
| `alarms[].level` | `critical` / `warning` / `info` |

## PUT /api/mode

```json
{"mode": "auto"}
```

- 切到 `off`：阀门关到零点（位置不可信时先顶到底重新计数）
- 切到 `auto`：如果阀门低于起始开度，先开到起始开度，然后立即开始调节
- 切到 `manual`：阀门停在当前位置，等待手动指令

返回新的 status。

## PUT /api/target

```json
{"temperature": 52}
```

整数，范围 `target_range.min`–`target_range.max`。自动模式下主管回水被控制在 `[目标, 目标 + upper_band]`。立即生效，并持久化。

## PUT /api/night-saver

```json
{"enabled": true}
```

开启 / 关闭夜间节能，持久化。时段在 `config.json` 的 `night_saver.start` / `end` 设置（默认 `00:30`–`06:30`，可以跨午夜）。在时段内关闭会立即恢复当前模式。返回新的 status。

## POST /api/valve/move（仅手动模式）

```json
{"steps": 5}        // 相对移动，负数为关小
{"position": 40}    // 绝对位置，0..max
```

二者只能给一个，都是相对零点的开度（`position` 可以为负，最小 `valve.min`）。指令被接受后立即返回 `202` 和 status（`valve.manual_target` 是目标位置），阀门随后每 0.5 秒走一步。过热保护期间不允许开大（`409`）。

## POST /api/valve/calibrate（重新计数）

请求体 `{}`。阀门先完全关闭（多走 20 步顶到底）并把绝对位置清零，零点不变，然后恢复当前模式。约 1 分钟，期间 `busy = "calibrating"`。设置零点期间返回 `409`。

## 设置零点

| 请求 | 体 | 说明 |
|---|---|---|
| `POST /api/valve/zero/start` | `{}` | 开始：控制暂停，阀门关到底（`stage = "closing"`，`busy = "closing to end stop"`），完成后 `stage = "ready"`。已在进行中时无操作 |
| `POST /api/valve/zero/jog` | `{"steps": 5}` | 点动，−20..20 且不为 0；仅 `ready` 阶段，否则 `409`。位置限制在 0..`max_offset` |
| `POST /api/valve/zero/set` | `{}` | 把当前绝对位置设为零点并保存，恢复原模式；仅 `ready` 阶段 |
| `POST /api/valve/zero/cancel` | `{}` | 放弃，零点不变，恢复原模式 |

都返回 `202` 和 status。30 分钟未完成会自动取消。

## GET /api/history?hours=6&max_points=360

最近 `hours` 小时（最多 48）的数据，平均压缩到不超过 `max_points` 个点：

```json
{"hours": 6, "points": [
  {"t": 1792742028.75, "mainInlet": 75.0, "mainReturn": 55.0, "heatingInlet": 34.9,
   "heatingReturn": 30.0, "waterInlet": 45.0, "valve": 34, "mode": "auto"}
]}
```

## GET /api/events?limit=50

最近的事件（模式切换、目标温度修改、过热/无消耗/热水箱、传感器和继电器故障、校准），新的在前：

```json
{"events": [{"t": 1792742048.72, "kind": "mode", "level": "info", "message": "mode changed: auto -> manual"}]}
```
