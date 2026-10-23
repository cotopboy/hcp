# 从零重建控制器

控制器（树莓派、SD 卡、继电器板或传感器）坏了时，按本文一步步重建。整个过程不需要旧设备上的任何文件：代码在 Git 仓库里，传感器 ID 和参数在 [config.example.json](../config.example.json) 里。

> ⚠️ 阀门执行器通常接 230 V 交流电。继电器触点侧的接线请断电操作，不确定时请电工完成。

## 1. 硬件清单

| 部件 | 规格 / 说明 |
|---|---|
| 树莓派 | 原来是 Raspberry Pi 4 Model B（Rev 1.5）。任何带 40 针 GPIO、能跑 Raspberry Pi OS Bookworm 的型号都行（3B+、4、5、Zero 2 W） |
| 电源 | 官方电源（Pi 4：5 V / 3 A USB‑C） |
| microSD 卡 | 16 GB 以上，A1 级别；建议备一张写好系统的备用卡 |
| I²C 继电器板 | 地址 `0x10`，寄存器 `0x01`…`0x04` 各控制一路继电器，写 `0xFF` 吸合、`0x00` 释放。从地址和寄存器的用法判断，原板很可能是 **52Pi DockerPi 4 Channel Relay（EP‑0099）**——请对照实物确认。只用到第 1、2 路 |
| DS18B20 × 5 | 防水不锈钢探头型（3 线：红 VCC、黑 GND、黄/白 DATA），用导热胶 + 扎带/保温棉固定在管道外壁 |
| 4.7 kΩ 电阻 × 1 | 1‑Wire 总线上拉（DATA 到 3.3 V）。有些传感器转接板自带 |
| 电动混水阀执行器 | 三线浮点式（开 / 关 / 公共）。全行程约 60 秒（对应 `full_stroke_pulses = 120`）；更换型号后需重新测量，见第 6 步 |

## 2. 接线

### 树莓派引脚

| 物理引脚 | 功能 | 接到 |
|---|---|---|
| 1 | 3.3 V | 所有 DS18B20 红线；4.7 kΩ 电阻一端 |
| 6 | GND | 所有 DS18B20 黑线 |
| 7 | GPIO4（1‑Wire） | 所有 DS18B20 数据线并联；4.7 kΩ 电阻另一端 |
| 3 / 5 | SDA / SCL（I²C 总线 1） | 继电器板（若是 HAT 形式直接插在 40 针上即可） |

```
3.3V (pin 1) ──┬───────────────┬── DS18B20 #1..#5 VCC (红)
               │               │
             [4k7]             │
               │               │
GPIO4 (pin 7) ─┴── DATA (黄) ──┘  （5 个传感器并联在同一根总线上）
GND (pin 6) ─────── GND (黑)
```

### 继电器 → 阀门执行器

| 继电器 | 寄存器 | 功能 | 接线 |
|---|---|---|---|
| 第 1 路 | `0x01`（`register_up`） | 开大阀门 | COM 接 L（火线），NO 接执行器「开」端子 |
| 第 2 路 | `0x02`（`register_down`） | 关小阀门 | COM 接 L，NO 接执行器「关」端子 |
| — | — | — | 执行器 N（零线）直接接 N |

软件保证两路不会同时吸合（先断另一路，换向前暂停 0.5 秒）。如果装好后发现方向反了，不用改线，把 `config.json` 里的 `register_up` / `register_down` 对调即可。

## 3. 安装系统

1. 用 [Raspberry Pi Imager](https://www.raspberrypi.com/software/) 写入 **Raspberry Pi OS Lite（64‑bit，Bookworm）**。
2. 在 Imager 的「编辑设置」里：主机名填 `hcp`，设置用户名和密码（例如 `pi`），配置 Wi‑Fi（或用网线），**勾选启用 SSH**。
3. 插卡上电，等 1–2 分钟后在电脑上测试：

```bash
ssh pi@hcp.local
```

4. 建议在路由器里给树莓派分配固定 IP（DHCP 保留）。App 能自动发现控制器，但固定 IP 便于手动连接和部署。

## 4. 部署程序

在 Mac 上（仓库根目录）：

```bash
./scripts/deploy.sh pi@hcp.local
```

在 Windows 上（PowerShell，仓库根目录；需要系统自带的 OpenSSH 客户端）：

```powershell
.\scripts\deploy.ps1 -Target pi@hcp.local
```

第一次部署后，在树莓派上完成安装（安装 `python3-smbus`、`i2c-tools`、`avahi-daemon`，启用 I²C 和 1‑Wire，注册 systemd 服务和 Bonjour 广播，从示例生成 `config.json`）：

```bash
ssh -t pi@hcp.local 'cd hcp && sudo ./deploy/install.sh'
```

脚本提示需要重启时：

```bash
ssh pi@hcp.local sudo reboot
```

以后每次修改代码只需再运行一次 `deploy.sh` / `deploy.ps1`：它会先跑单元测试，上传，然后重启服务。树莓派上的 `config.json` 和 `data/` 不会被覆盖。

## 5. 识别传感器

先停掉服务，避免它在调试期间动阀门：

```bash
sudo systemctl stop hcp
```

列出总线上的传感器（应该有 5 个 `28-…`）：

```bash
ls /sys/bus/w1/devices/
```

逐个读数：

```bash
for d in /sys/bus/w1/devices/28-*; do echo "$d $(grep -o 't=.*' $d/w1_slave)"; done
```

如果换了新传感器，ID 会变。用手握住（或用热水杯贴住）一个探头，再运行上面的命令，读数上升的那个就是它。把 ID 填进 `~/hcp/config.json` 的 `sensors.ids`：

| 键 | 安装位置 |
|---|---|
| `mainInlet` | 主管道（一次侧）进水 |
| `mainReturn` | 主管道（一次侧）回水 ← 控制的主要依据 |
| `heatingInlet` | 混水阀之后，暖气回路进水 |
| `heatingReturn` | 暖气回路回水 |
| `waterInlet` | 热水箱进水 |

原来的 ID 记录在 [config.example.json](../config.example.json)。

## 6. 检查继电器和阀门行程

```bash
sudo i2cdetect -y 1
```

表中应出现 `10`。看不到就检查 I²C 是否启用（`sudo raspi-config nonint get_i2c` 输出 `0` 表示已启用）和接线。

点动测试（服务必须是停止状态，脚本会检查）：

```bash
~/hcp/scripts/relay_test.sh up 3
```

```bash
~/hcp/scripts/relay_test.sh down 3
```

观察执行器上的指针确认方向。

**测量全行程**（更换了执行器时需要）：先 `relay_test.sh down 90` 关到底，再用秒表计时 `relay_test.sh up 90` 直到指针到全开。`full_stroke_pulses` = 秒数 × 2，写进 `config.json` 的 `valve` 部分。如果全行程与 60 秒差别很大，`ready_position`、`auto_min`、`auto_max`、`reduced_position` 也应按比例缩放（它们都是「步」）。

## 7. 启动并验证

```bash
sudo systemctl start hcp
```

```bash
journalctl -u hcp -f
```

正常启动时会看到：`HCP 2.0.0 starting` → 每 10 秒一行温度 → `closing valve fully … to calibrate` → `valve calibrated` → `valve up 34 pulse(s)`。

在局域网中任何电脑上：

```bash
curl http://hcp.local:8080/api/status
```

## 8. 安装 iPhone App

见 [ios/README.md](../ios/README.md)。App 打开后会自动在局域网中找到「HCP on hcp」。

## 9. 需要备份什么

| 内容 | 位置（树莓派） | 是否重要 |
|---|---|---|
| 配置（传感器 ID、参数） | `~/hcp/config.json` | **重要**。改过以后复制一份到电脑，或把改动同步回 `config.example.json` 并提交到 Git |
| 运行状态 | `~/hcp/data/state.json` | 不重要：丢失后用默认值启动并重新校准，模式和目标温度在 App 里重新设一下即可 |
| 温度记录 | `~/hcp/data/logs/temperature_YYYYMMDD.csv` | 可选 |
| 应用日志 | `~/hcp/data/logs/hcp.log`（5 MB × 5 滚动），以及 `journalctl -u hcp` | 排查问题用 |

拉取备份：

```bash
scp pi@hcp.local:hcp/config.json ./config.backup.json
```

## 10. 故障排查

| 现象 | 检查 |
|---|---|
| App 找不到控制器 | 手机和树莓派是否在同一网络（访客网络通常隔离）；iPhone「设置 → 隐私与安全性 → 本地网络」里是否允许了「暖气」；改用手动输入 IP:8080；`systemctl status avahi-daemon` |
| App 显示「连接不上控制器」 | `systemctl status hcp`；`journalctl -u hcp -n 50`；端口是否被改过 |
| 某个温度显示「无读数」 | 该探头接线 / 防水接头进水；`ls /sys/bus/w1/devices/` 是否还在；ID 是否填错 |
| 所有温度都没有读数 | 1‑Wire 未启用（`sudo raspi-config nonint get_onewire` 应为 `0`）；上拉电阻；总线短路 |
| 「继电器故障」 | `i2cdetect -y 1` 是否还能看到 `0x10`；继电器板供电；用户是否在 `i2c` 组（`groups pi`） |
| 阀门位置明显不准 | App →「校准阀门…」 |
| 启动报 `config error` | 按提示修正 `config.json`（键名拼写、类型、位置大小关系） |
| 服务反复重启 | `journalctl -u hcp -b` 看第一条错误 |

## 11. 在电脑上试运行（不接硬件）

```bash
python3 -m hcp --simulate
```

用模拟的传感器和继电器启动完整控制器和 API（端口 8080，数据写在 `data-sim/`），可以用 App 或 `scripts/hcpctl.sh` 连接调试。
