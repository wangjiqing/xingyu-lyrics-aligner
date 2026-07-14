# macOS 无签名安装说明

v0.7.0 macOS Desktop 候选包仅支持 Apple Silicon（arm64）和 macOS 14 或
更高版本。它没有使用 Apple Developer ID 签名，也没有经过 Apple
notarization。Bundle 内部使用的 ad-hoc 签名只保证被修改 Mach-O 的一致性，
不建立 Apple 开发者身份或 Gatekeeper 信任。

## 正常安装

1. 打开 `星语歌词对齐器-0.7.0-arm64-unsigned.dmg`。
2. 将“星语歌词对齐器”拖入 `Applications`。
3. 首次启动。
4. 如果 macOS 阻止打开，进入“系统设置 → 隐私与安全性”。
5. 在与星语歌词对齐器对应的提示处选择“仍要打开”，再确认一次。

仅当你已经确认 DMG 来源可信时，先完全退出 App，再使用备用命令：

```bash
xattr -dr com.apple.quarantine "/Applications/星语歌词对齐器.app"
```

这会移除该 App 的 quarantine 标记。不要对未知来源软件执行，也不要使用
`sudo spctl --master-disable` 关闭整个系统 Gatekeeper。正常写入 Applications
时通常也不需要 `sudo`。

## 本地数据与磁盘空间

音频和歌词在本机处理，不上传。DMG 不包含模型权重；首次使用由用户确认后
下载约 1.28 GB 的必需中文对齐模型。人声/伴奏导出另需约 84 MB 的可选
Demucs 模型。模型保存在：

```text
~/Library/Application Support/XingyuLyricsAligner/Models/
```

替换或删除 `.app` 不会删除该目录。当前候选 App 的逻辑文件大小约 979 MiB，
DMG 约 273 MiB；实际精确字节数记录在候选的 release manifest 中。任务还会产生
受控音频副本、中间 WAV 和结果文件，请额外预留空间。
