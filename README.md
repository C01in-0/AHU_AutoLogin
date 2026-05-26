# AHU AutoLogin（安大校园网无感连网引擎）

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)]()
[![Language](https://img.shields.io/badge/language-Python-brightgreen.svg)]()

**作者：Colin**  
**版本：v1.1.0**  
**平台：Windows**  
**适配环境：安徽大学校园网 Dr.COM / ePortal Portal**

你还在为每次启动电脑的登录认证苦恼吗？

你还在为系统玄学提示“AC认证失败，请检查账号密码”而怒锤键盘吗？

抛弃那些反人类的登录认证吧。插上网线的瞬间，让代码替你把校园网认证包踹进网关。

---

## 🟢 小白专区：开箱即用

无需懂代码，不用配置 Python 环境。严格按照下面步骤来，半分钟即可部署。

### 1. 下载工具包

进入本项目 GitHub Releases 页面，下载最新版：

```text
AHU_AutoLogin_v1.1.0.zip
```

如果 GitHub 访问较慢，可以稍后重试，或者通过镜像 / 加速链接下载 Release 附件。

---

### 2. 解压工具包

将下载的 `.zip` 压缩包彻底解压到电脑里的固定文件夹。

建议路径：

```text
D:\Tools\AHU_AutoLogin
```

注意：

> 绝对不要在压缩包里直接双击运行。必须先完整解压。

---

### 3. 一键注入系统

进入解压后的文件夹，找到：

```text
install.bat
```

右键点击它，选择：

```text
以管理员身份运行
```

然后在弹出的窗口中按提示输入：

```text
校园网账号
校园网密码
```

安装程序会自动完成：

- 生成本地 `.env` 配置文件；
- 创建 Windows 任务计划 `AHU_AutoLogin`；
- 绑定网络事件 `Event ID 10000`；
- 设置后台 SYSTEM 身份运行；
- 自动试运行一次认证引擎。

看到：

```text
[OK] 部署完成
```

即可关闭窗口。

---

### 4. 享受无感连网

配置到此结束。

你可以拔掉网线再插上试试。正常情况下，不需要打开认证网页，不需要手动点登录。系统在检测到网络连接建立后，会自动拉起认证引擎，完成校园网 Portal 登录。

如果日志中出现：

```text
login response: status=200
ret_code":2
```

通常表示当前 IP 已经在线，或者重复认证成功。

---

## 🔴 进阶专区：底层架构与逆向剖析

本项目是对 AHU 校园网 Web Portal 认证机制的一次黑盒逆向与工程化重构，目标是提供比传统“死循环 ping 外网”更优雅、更轻量的系统级解决方案。

---

### 1. 认证机制逆向：JSONP on Port 801

抓包分析显示，当前 AHU Portal 网关在 `801` 端口开放认证接口。

旧版曾使用：

```text
/eportal/portal/login
```

但当前环境下该路径会返回：

```text
404 Not Found
```

v1.1.0 已经修正为当前可用接口：

```text
http://172.16.253.3:801/eportal/
```

并通过 GET 参数携带：

```text
c=Portal
a=login
user_account=你的账号
user_password=你的密码
wlan_user_ip=本机校园网 IP
```

该接口返回 JSONP 风格响应，例如：

```text
dr1003({"result":"0","msg":"","ret_code":2})
```

其中 `ret_code=2` 通常表示当前 IP 已经在线，可以视为成功状态。

---

### 2. 零感知事件驱动：Event-Driven Hook

本工具不采用常驻后台死循环。

旧式方案通常是：

```python
while True:
    ping()
    sleep()
```

能用，但丑。平时一直挂后台，多少有点像拿电饭煲煮一粒米。

AHU AutoLogin 使用 Windows 任务计划程序，将认证引擎绑定到：

```text
Microsoft-Windows-NetworkProfile/Operational
Event ID 10000
```

也就是网络连接建立事件。

平时没有常驻进程，CPU 和内存占用为 0。只有当 Windows 检测到网络连接变化时，才会短暂唤醒 `login.exe` 完成认证。

---

### 3. 多网卡等待与路由纠偏

很多电脑同时存在：

- 有线网卡；
- WLAN；
- VMware 虚拟网卡；
- WSL / Hyper-V 虚拟网卡；
- 蓝牙网络；
- Clash / Mihomo 虚拟网络环境。

插入网线的瞬间，DHCP 分配和 Windows 路由表更新需要时间。脚本如果跑得太快，可能先拿到 WLAN 或虚拟网卡 IP，导致认证失败。

v1.1.0 的处理方式是：

1. 直接探测 AHU Portal 网关 `172.16.253.3:801`；
2. 获取当前通往该网关的本机出口 IP；
3. 判断 IP 是否属于校园网段；
4. 如果不是，则继续等待；
5. 直到识别出真实有线校园网 IP 后再发包。

当前默认识别：

```text
10.
172.16.
172.21.
```

对应配置：

```text
CAMPUS_IP_PREFIXES=10.,172.16.,172.21.
```

---

### 4. 凭证隔离：Credential Decoupling

账号密码不硬编码在程序中。

安装时输入的校园网账号密码会写入本地：

```text
.env
```

主程序运行时读取 `.env`，再向 Portal 网关发送认证请求。

`.env` 只存在你的本地电脑中，不会上传到云端，也不会被程序发送到除校园网 Portal 网关以外的地方。

注意：

> 不要把 `.env` 上传到 GitHub，不要截图发给别人，不要塞进压缩包分享。

---

### 5. 单体静默运行：Silent Execution

核心认证引擎由 Python 编写，并通过 PyInstaller 打包为：

```text
login.exe
```

发布包用户不需要安装 Python，也不需要安装 requests 等依赖。

任务计划运行时会静默调用 `login.exe`，不会弹黑框，不会干扰正常使用。

---

## 💻 文件说明

发布包中包含：

```text
login.exe          核心认证引擎
install.bat        小白入口，右键管理员运行
install.ps1        安装逻辑
uninstall.bat      卸载任务计划
clear_proxy.ps1    清理系统代理残留
.env.example       配置模板
README.md          使用说明
```

安装后会生成：

```text
.env               本地账号密码配置
autologin.log      运行日志
```

其中 `.env` 保存你的校园网账号和密码，只存在本地。不要上传、不要截图、不要发给别人。

---

## 🛠 源码编译与二次开发

如果你想自己编译：

```bash
git clone https://github.com/C01in-0/AHU_AutoLogin.git
cd AHU_AutoLogin
pip install requests pyinstaller
pyinstaller --noconsole --onefile --name login login.pyw
```

编译结果在：

```text
dist/login.exe
```

---

## ❓ 常见问题 Q&A

### Q1：周末回家插上家里网线，或者连别人手机热点，这个工具会发癫吗？

一般不会。

任务可能会被网络事件唤醒，但认证引擎会优先尝试连接 AHU Portal 网关：

```text
172.16.253.3:801
```

如果当前网络不是校园网，请求会超时或取不到有效校园网 IP，程序会静默退出。

---

### Q2：网已经通了，为什么校园网登录网页有时候还是会弹出来？

因为 Windows 自带的 NCSI 探测比脚本更急。

Windows 会抢先访问自己的联网检测地址。如果此时 Portal 还没放行，它可能会被网关劫持，于是系统弹出认证页。

但实际上，当你看到页面时，后台脚本可能已经把认证包发完了。只要外网能访问，就不用理那个网页。

---

### Q3：日志里的 `ret_code=2` 是失败吗？

通常不是。

`ret_code=2` 多数情况下表示：

```text
当前 IP 已经在线
```

也就是重复认证或已经认证成功。

如果浏览器能打开网页，看到它就当正常。

---

### Q4：插网线后日志里先出现 WLAN IP，后来才出现 172.21.x.x，正常吗？

正常。

插网线后，Windows 路由表和 DHCP 状态不是瞬间稳定的。脚本会等待真实校园网有线 IP 出现，再认证。

这就是为什么 v1.1.0 不再只做“一次探测，一次发包”。

---

### Q5：校园网已经自动连上，微信能用，但浏览器打不开网页，关闭系统代理后立刻正常？

这通常不是校园网认证失败，而是 Windows 系统代理残留导致的。

如果你之前使用过 Clash / Mihomo / 其他代理工具，Windows 可能仍然保留：

```text
127.0.0.1:7890
```

此时如果代理客户端没有启动，浏览器会继续把流量发给一个不存在的本地代理端口，于是网页打不开。

解决方式：

运行本包中的：

```text
clear_proxy.ps1
```

或者手动关闭：

```text
控制面板 → Internet 选项 → 连接 → 局域网设置 → 取消“为 LAN 使用代理服务器”
```

安装时如果选择创建 `Clear_User_Proxy_On_Logon`，每次登录 Windows 时也会自动清理代理残留。

---

### Q6：能否彻底阻止校园网认证网页弹出？

目前经过十几台电脑的测试，网页不会主动弹出，如果仍有“余孽”，可以使用以下方案，但不建议小白乱动。

通过关闭 Windows NCSI 主动探测减少强制门户弹窗：

```text
HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\NlaSvc\Parameters\Internet
EnableActiveProbing = 0
```

代价是：以后去酒店、机场、咖啡厅这类需要网页认证的 Wi-Fi，系统也可能不会主动弹出登录页。你需要手动访问一个纯 HTTP 网站来触发跳转。

---

### Q7：怎么卸载？

右键运行：

```text
uninstall.bat
```

它会删除：

```text
AHU_AutoLogin
```

这个任务计划。

然后直接删除整个工具文件夹即可。

如果你创建过代理清理任务，也可以手动执行：

```powershell
schtasks /delete /tn "Clear_User_Proxy_On_Logon" /f
```

---

## 🔐 安全说明

1. 账号密码只保存在本地 `.env`；
2. 程序不会上传任何信息到第三方服务器；
3. 程序只向 AHU 校园网 Portal 网关发送认证请求；
4. `.env` 不要上传、不要截图、不要分享；
5. 如果你要二次开发，请确保 `.gitignore` 中包含 `.env`。

---

## 🧾 更新记录

### v1.0.1
- 移除旧版 mshta 自提权写法；
- 改成更稳的管理员权限检测；
- 如果不是管理员运行，就给出明确提示/自动用 PowerShell 重新拉起；
- 增加 login.exe 是否存在、任务创建是否成功的检查；
- 避免 Win11 下直接闪退，失败时保留错误信息。

### v1.1.0

- 修复旧版 `/eportal/portal/login` 返回 404 的问题；
- 当前认证入口适配为 `/eportal/?c=Portal&a=login`；
- 新增 `172.21.x.x` 校园网 IP 段支持；
- 优化多网卡、WLAN、VMware、WSL 环境下的 IP 识别；
- 将 `ret_code=2` 识别为已在线状态；
- 安装方式改为 `install.bat + install.ps1`；
- 新增 `clear_proxy.ps1` 处理 Clash / Mihomo 系统代理残留；
- 改进日志输出，便于排障。

---

## 💖 鸣谢与支持

如果这个小工具帮你每天省下了宝贵的十几秒，欢迎在项目右上角点一个免费的 Star。  
这是本人和校园网这个老古董斗智斗勇的最大动力。

作者：Colin

---

## License

MIT License
