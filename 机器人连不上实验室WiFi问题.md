# TonyPi
幻尔机器人版本备份


# 🧠 Raspberry Pi WiFi 修复与稳定化全过程记录（实验室网络）

## 📌 一、问题背景

最初系统存在以下问题：

### ❌ WiFi 混乱
- 存在多个 WiFi profile（0707 / HUAWEI-70 / 临时连接）
- NetworkManager 自动选择网络，导致“乱连”

### ❌ 自动连接冲突
系统会基于：
- 信号强度
- 最近使用记录
- 优先级

导致 WiFi 不稳定切换

### ❌ 临时连接污染
使用 `nmcli dev wifi connect` 会生成临时 UUID 连接，进一步增加混乱

---

## 🔧 二、完整修复过程

---

## 1️⃣ 删除旧 WiFi（清理污染）

```bash
sudo nmcli connection delete 0707
````

### 作用：

* 删除错误 WiFi profile
* 防止系统回连旧网络

---

## 2️⃣ 重新连接实验室 WiFi

```bash
sudo nmcli dev wifi connect "HUAWEI-70" password "******"
```

### 作用：

* 生成干净 WiFi profile
* 建立正确连接记录

---

## 3️⃣ 设置自动连接 + 优先级

```bash
sudo nmcli connection modify HUAWEI-70 connection.autoconnect yes
sudo nmcli connection modify HUAWEI-70 connection.autoconnect-priority 100
```

### 作用：

| 参数              | 功能      |
| --------------- | ------- |
| autoconnect yes | 开机自动连接  |
| priority 100    | 提高连接优先级 |

---

## 4️⃣ 绑定网卡（锁定 wlan0）

```bash
sudo nmcli connection modify HUAWEI-70 connection.interface-name wlan0
```

### 作用：

* 防止系统切换到虚拟网卡（p2p-dev-wlan0）
* 强制使用真实 WiFi 接口

---

## 5️⃣ 清理 NetworkManager 缓存

```bash
sudo rm -rf /var/lib/NetworkManager/*
sudo systemctl restart NetworkManager
```

### 作用：

* 清除残留 WiFi 配置
* 重建干净网络状态

---

## 6️⃣ 创建 WiFi 自动修复脚本

```bash
#!/bin/bash

while true; do
    nmcli connection up HUAWEI-70 2>/dev/null
    sleep 10
done
```

### 作用：

* WiFi 掉线自动重连
* 保持网络持续在线

---

## 7️⃣ systemd 守护进程

```ini
[Unit]
Description=WiFi Auto Repair
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/wifi-guard.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 作用：

* 开机自动启动脚本
* 脚本崩溃自动重启

---

## 8️⃣ 修复 systemd 启动失败问题

### 问题：

```
start-limit-hit
```

### 修复：

```ini
RestartSec=5
Type=simple
```

### 作用：

* 防止快速重启触发 systemd 限制

---

## 9️⃣ 修复脚本拼写错误

### 问题：

```
ture ❌
true ✔
```

### 作用：

* 修复脚本提前退出问题
* 解决 systemd 无限重启

---

## 🔒 10️⃣ WiFi 工业级限制策略

```ini
wifi.new-connections=standard
```

### 作用：

| 模式       | 行为             |
| -------- | -------------- |
| never    | 禁止新 WiFi（过于严格） |
| standard | 推荐（允许手动连接）     |

---

## 🧠 三、最终系统状态

当前系统已稳定为：

### 🟢 WiFi结构

* 唯一主网络：HUAWEI-70
* 旧网络：0707（已删除）
* 自动连接：已启用

### 🟢 网络行为

* 开机自动连接 HUAWEI-70
* 掉线自动恢复
* 不会回连旧 WiFi

### 🟢 系统稳定性

* NetworkManager 正常
* systemd 守护运行
* SSH / VNC 可稳定使用

---

## 🚀 四、系统架构总结

```
树莓派
 ├── HUAWEI-70（主网络）
 │     ├── SSH
 │     ├── VNC
 │     └── ROS通信
 │
 ├── WiFi Guard（systemd）
 │     └── 自动恢复网络
 │
 └── NetworkManager
       └── 管理连接策略
```

---

## 🎯 五、核心成果

✔ 清理错误 WiFi
✔ 修复自动连接冲突
✔ 建立稳定主网络
✔ 添加自动恢复机制
✔ 防止未来 WiFi 混乱

---

## 🧠 一句话总结

> 将树莓派从“自动混乱 WiFi 模式”修复为“单主网络 + 自动恢复的稳定控制系统”

```

---


```
