# 暖气 iPhone App（HCPRemote）

SwiftUI 写的个人用 App，在家庭局域网中控制 HCP 控制器：

- 自动发现控制器（Bonjour `_hcp._tcp`），也可手动输入 `IP:端口`
- 查看 5 路温度、阀门开度、当前状态和提醒（过热、传感器故障等）
- 切换 关闭 / 自动 / 手动
- 自动模式：调节主管回水目标温度
- 手动模式：±1 / ±10 步或滑块设定阀门位置
- 校准阀门、查看温度曲线（1–48 小时）和事件记录

要求：Xcode 16 或更新，iOS 17 或更新。

## 装到自己的 iPhone

1. 用 Xcode 打开 `ios/HCPRemote/HCPRemote.xcodeproj`。
2. 选中项目 → Target「HCPRemote」→ Signing & Capabilities：Team 选你的 Apple ID（Xcode → Settings → Accounts 里先登录）。如果提示 Bundle Identifier 冲突，把 `com.cotopboy.hcpremote` 改成任意唯一值。
3. 用数据线连接 iPhone，在 iPhone 上打开「设置 → 隐私与安全性 → 开发者模式」（首次需要重启手机）。
4. Xcode 顶部选择你的 iPhone，点 ▶︎ 运行。
5. 首次打开时允许「本地网络」权限，然后在列表中点控制器即可。

签名有效期：免费 Apple ID 签出的 App **7 天后**无法打开，需要连上 Xcode 再运行一次；付费开发者账号为 1 年（也可以用 TestFlight）。

## 开发

在 Mac 上不接硬件调试：

```bash
python3 -m hcp --simulate
```

在 iOS 模拟器里运行 App，手动输入 `127.0.0.1:8080`。想测试自动发现，可以在 Mac 上广播服务：

```bash
dns-sd -R "HCP on Mac" _hcp._tcp local 8080
```

结构：

| 文件 | 内容 |
|---|---|
| `Model/APIModels.swift` | API 的 JSON 模型和中文显示文字 |
| `Model/HCPClient.swift` | HTTP 请求 |
| `Model/ControllerStore.swift` | App 状态、每 3 秒轮询、发送指令 |
| `Model/ServiceDiscovery.swift` | Bonjour 搜索和解析 |
| `Views/` | 主界面、各控制区块、曲线、事件、连接设置 |

接口说明见 [docs/API.md](../docs/API.md)。
