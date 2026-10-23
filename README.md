# HCP — 树莓派供暖阀门控制器

HCP（Heating Control）运行在家里的 **树莓派** 上：通过 5 个 **DS18B20** 温度传感器监测主管道、暖气回路和热水箱的温度，通过 **I²C 继电器板** 驱动电动混水阀，把主管回水温度控制在设定范围内，并处理过热、无热量消耗、热水箱加热等工况。

v2 起控制器提供局域网 HTTP API，配套 **iPhone App**（[ios/](ios/README.md)）可以：

- 查看各路温度、阀门开度、运行状态和提醒
- 切换 **关闭 / 自动 / 手动**
- 自动模式下调节目标温度（暖气大小）
- 手动模式下直接开大 / 关小阀门
- 设置阀门零点（刚有水流的位置）、重新计数、查看温度曲线和事件记录

| 文档 | 内容 |
|---|---|
| [docs/REBUILD.md](docs/REBUILD.md) | **控制器坏了怎么办**：硬件清单、接线、装系统、部署、识别传感器、测试、备份、排查 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 模块、线程、阀门模型、控制规则、特殊工况、故障处理、相对 v1 的修复和行为变化 |
| [docs/API.md](docs/API.md) | HTTP 接口 |
| [ios/README.md](ios/README.md) | 把 App 装到 iPhone |
| [docs/v1-overview.html](docs/v1-overview.html) | 旧版（v1）的图表说明，仅供参考 |

## 目录

```
hcp/                 Python 控制器（只依赖标准库 + python3-smbus）
tests/               单元测试：python3 -m unittest discover -s tests -t .
deploy/              树莓派上的安装脚本、systemd 服务、Bonjour 广播
scripts/             deploy.sh（Mac）、deploy.ps1（Windows）、hcpctl.sh（命令行控制）、relay_test.sh（硬件调试）
config.example.json  配置示例（含当前传感器 ID）；树莓派上复制为 config.json
ios/HCPRemote/       iPhone App（SwiftUI）
data/                运行时生成：state.json、logs/（不进 Git）
```

## 日常使用

部署（会先跑测试，然后上传并重启服务）：

```bash
./scripts/deploy.sh pi@hcp.local
```

Windows：

```powershell
.\scripts\deploy.ps1 -Target pi@hcp.local
```

命令行查看状态 / 控制（任何局域网内的电脑）：

```bash
HCP_URL=http://hcp.local:8080 ./scripts/hcpctl.sh status
```

树莓派上看日志：

```bash
journalctl -u hcp -f
```

## 从 v1 升级

1. 停掉旧程序并去掉它的自动启动方式（`sudo pkill -f hcpmain.py`，再检查 `crontab -e`、`sudo crontab -e`、`/etc/rc.local` 里启动 `hcpmain.py` 的那一行）。两个程序同时控制阀门会出问题，`install.sh` 检测到旧程序在运行时会停止安装。
2. 部署到原来的目录（默认 `~/hcp`），然后运行 `sudo ./deploy/install.sh`（见 [REBUILD.md 第 4 步](docs/REBUILD.md#4-部署程序)）。
3. 首次启动会从旧的 `settings/target_temperature.txt` 和 `settings/heating_active.txt` 迁移目标温度和开关状态，然后把阀门完全关闭重新校准（约 1 分钟），再开始自动调节。旧的 `.py` 文件和 `settings/` 可以之后手动删除。
4. 温度记录改名为 `data/logs/temperature_YYYYMMDD.csv`，多了阀门位置和模式两列。

## 开发

```bash
python3 -m unittest discover -s tests -t .
```

不接硬件运行完整控制器（模拟传感器和继电器，数据在 `data-sim/`）：

```bash
python3 -m hcp --simulate
```
