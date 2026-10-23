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
    "position": 34, "max": 120, "percent": 28,
    "auto_min": 35, "auto_max": 66, "reduced": 25,
    "manual_target": null, "moving": null, "calibrated": true
  },
  "last_decision": {"op": "hold", "rule": "in_range", "reason": "within target range",
                    "moved": false, "at_limit": false, "at": 1792742047.84},
  "alarms": []
}
```

| 字段 | 取值 |
|---|---|
| `mode` | `off` 关闭 / `auto` 自动 / `manual` 手动 |
| `phase` | `idle`（关闭）、`manual`、`normal`（自动调节）、`water_tank`（热水箱加热，自动暂停）、`no_consumption`（无热量消耗，阀门在低开度）、`overheat`（过热保护）、`sensor_fault`（必需传感器无读数，阀门保持不动）、`relay_fault`（继电器写入失败） |
| `busy` | 正在执行的长动作：`calibrating`、`closing`、`opening to ready position`、`overheat protection`，否则 `null` |
| `temperatures.*.value` | °C；传感器故障或读数超过 60 秒未更新时为 `null` |
| `valve.position` | 阀门位置，单位「步」（继电器通电 0.5 秒），0 = 完全关闭 |
| `valve.moving` | `up` / `down` / `null` |
| `last_decision.rule` | `heating_inlet_low`、`sum_low`、`below_target`、`sum_high`、`above_target`、`in_range`（见 [ARCHITECTURE.md](ARCHITECTURE.md#5-自动控制)） |
| `alarms[].code` | `relay_fault`、`overheat`、`no_consumption`、`water_tank`、`sensor_fault`（带 `sensor` 字段）、`uncalibrated` |
| `alarms[].level` | `critical` / `warning` / `info` |

## PUT /api/mode

```json
{"mode": "auto"}
```

- 切到 `off`：阀门完全关闭（同时重新校准位置）
- 切到 `auto`：如果阀门低于起始开度，先开到起始开度，然后立即开始调节
- 切到 `manual`：阀门停在当前位置，等待手动指令

返回新的 status。

## PUT /api/target

```json
{"temperature": 52}
```

整数，范围 `target_range.min`–`target_range.max`。自动模式下主管回水被控制在 `[目标, 目标 + upper_band]`。立即生效，并持久化。

## POST /api/valve/move（仅手动模式）

```json
{"steps": 5}        // 相对移动，负数为关小
{"position": 40}    // 绝对位置，0..max
```

二者只能给一个。指令被接受后立即返回 `202` 和 status（`valve.manual_target` 是目标位置），阀门随后每 0.5 秒走一步。过热保护期间不允许开大（`409`）。

## POST /api/valve/calibrate

请求体 `{}`。阀门先完全关闭（多走 20 步顶到底）并把位置清零，然后恢复当前模式。约 1 分钟，期间 `busy = "calibrating"`。

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
