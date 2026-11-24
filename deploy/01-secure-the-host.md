# 01 · 上机前加固（腾讯云轻量应用服务器 Lighthouse）

**目标**：在把 Watchtower 传上云之前，先把这台机器的门关好。

> ⚠️ 这台是**轻量应用服务器（Lighthouse）**，不是 CVM。轻量云用实例级「**防火墙**」，**没有「安全组」**；救命通道是实例卡片上的「**登录**」（OrcaTerm 网页终端），不是 VNC。

## 这台机器已确认的信息

| 项 | 值 | 来源 |
| --- | --- | --- |
| 机型 | 腾讯云轻量应用服务器 | 控制台截图 |
| 系统 | **Ubuntu 24.04.5 LTS (Noble Numbat)** | `cat /etc/os-release` |
| 当前登录用户 | **`ubuntu`**（非 root，`sudo` 可用） | `whoami` / `sudo grep` 执行成功 |
| 地域 / 配置 | 北京 · 2 核 2 GB / 40 GB 系统盘 | 控制台截图 |
| 到期 | **2026-12-08** | 控制台截图 |
| SSH 密码登录 | **当前是开着的** | 见下 |

2 核 2G 跑 Flask + SQLite + Nginx 绰绰有余。**只剩 26 天到期**，所以每一步都写进文档——将来续费或换机器照着敲能重建，这本身就是运维里「可复现」的基本功，也是你以后能交给客户的交付物。

> 这些命令跑在你的服务器上。我这边没有访问权限，不代跑，也不会说「已验证」。把每步输出（**公网 IP 打码**）发我，我把后续命令调准。

---

## 本轮探测结论：密码是被谁打开的

你贴出来的 `grep` 结果里，**只有三行真正生效**，其余都不是：

| 文件 / 行 | 是否生效 | 说明 |
| --- | --- | --- |
| `/etc/ssh/sshd_config.d/50-cloud-init.conf` → `PasswordAuthentication yes` | ✅ **生效，而且是元凶** | cloud-init 的 drop-in 文件，通过主配置顶部的 `Include` 加载 |
| `/etc/ssh/sshd_config` → `PermitRootLogin yes` | ✅ 生效 | root 可以直接登录 |
| `/etc/ssh/sshd_config` → `PasswordAuthentication yes` | ✅ 生效 | 密码登录开着 |
| `/etc/ssh/ssh_config` → `# PasswordAuthentication yes` | ❌ | 这是 **ssh 客户端**配置（`ssh_config`，没有 d），且被注释 |
| `/etc/ssh/sshd_config.ucf-dist` → 各种 | ❌ | dpkg 留下的**样例文件**，sshd 根本不读 |
| 主配置里 `#PasswordAuthentication yes` 等 | ❌ | 注释行 |

**这正是最常见的踩坑点**：只改 `/etc/ssh/sshd_config` 没用，`50-cloud-init.conf` 会把它压回去。OpenSSH 对这类关键字采用「**先出现的值生效**」（first obtained value wins），而 `Include /etc/ssh/sshd_config.d/*.conf` 排在主配置最前面，drop-in 文件按文件名数字顺序读入，`50-` 的值先拿到，主配置后面写 `no` 也不算数。

所以本手册第 4 步**两处都改**，并且用 `sshd -T` 看最终生效值来验收，而不是靠 `grep` 猜。

> 补充：`KbdInteractiveAuthentication` 是另一个可能绕过「禁密码」的口子，第 4 步一并关掉。

---

## 第 0 步：确认救命通道

**控制台 → 轻量云 → 服务器 → 点实例卡片「登录」**，会弹出 OrcaTerm 登录框。实测（2026-11-12 截图）这个框里有三种通道，**作用完全不同**：

| 入口 | 走什么 | 改坏 sshd / 封掉 22 后还能进吗 |
| --- | --- | --- |
| **免密连接（TAT）**（默认选中，用户名 `ubuntu`） | 腾讯云自动化助手 agent，走云 API 下发，是 agent **主动外连** | ✅ **能**。既不读 sshd 配置，也不走 22 入站端口 |
| 终端连接（SSH） | 走公网 SSH | ❌ 不能，会跟着 sshd 一起被锁 |
| 底部小字「VNC 登录」 | 真正的带外控制台，连 agent 都不依赖 | ✅ 理论上能，但通常要实例密码，禁密码后可能失效，别把它当主救命通道 |

**结论：TAT 才是这次的保命通道。** 第 4 步改 sshd、第 5 步开 ufw 之前，必须先用它真正进到系统里敲一次 `whoami`（看到 `ubuntu@VM-0-8-ubuntu:~$` 才算数，弹窗还停在「正在登录」不算）。

> 一个容易栽的坑：第 4 步要验证「密码登录被拒」，**必须在自己电脑上用 `ssh -o PubkeyAuthentication=no ...` 测**，别在 OrcaTerm 里点「终端连接（SSH）」测——后者走的是平台下发的临时凭证，测出来的结果不代表公网 SSH 的真实状态。

**没确认 TAT 能进系统之前，不要往下做。**

## 保命三条（贴在最显眼的地方）

1. **原来那个已登录的终端窗口全程不要关**，改坏了从旧窗口改回来。
2. **必须先用新密钥成功登录一次，才允许禁密码**。顺序反了就是把自己锁在门外。
3. **防火墙 `enable` 之前必须先放行 SSH**。顺序反了同样锁死。

---

## 1. 在自己电脑上生成密钥对

在**你自己的 Windows 电脑**上，先建目录再生成（⚠️ 不要在 OrcaTerm／服务器上生成，私钥不能留在服务器里）。

PowerShell（Windows 默认）：

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\watchtower_ed25519" -C "watchtower-admin"
```

Git Bash：

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/watchtower_ed25519 -C "watchtower-admin"
```

> 直接跑 `ssh-keygen -f ~/.ssh/...` 若报 `Saving key ... failed: No such file or directory`，就是 `.ssh` 目录还没建；`ssh-keygen` 不会自动创建父目录。上面两条命令已把它带上。本文后面所有 `~/.ssh/...` 在 PowerShell 里若也报路径错，改成 `$env:USERPROFILE\.ssh\...` 即可。

中途会问两次 `Enter passphrase (empty for no passphrase)` / `Enter same passphrase again`。**这是给私钥文件本身加密的本地口令，不是服务器密码，也不是登录密码。**

本轮建议**直接回车两次留空**，原因：私钥只放在你自己的电脑、不外传；后面第 4 步要反复用 `ssh -i` 做「密码被拒 / 密钥仍可登」双向验证，带了口令容易把「私钥解锁提示」误认成「服务器还在要密码」。等这套跑通、以后真机上存管理密钥时，再设口令并配 `ssh-agent` 记住。

⚠️ **口令没有找回机制**：忘了只能重新生成一对密钥、重传公钥。如果已经不小心输了内容，直接 `Ctrl+C` 取消重来最省事；事后想改可用 `ssh-keygen -p -f ~/.ssh/watchtower_ed25519`。

生成两个文件：

- `watchtower_ed25519` —— **私钥**，永不外传、不发聊天、不进 Git
- `watchtower_ed25519.pub` —— 公钥，可以复制粘贴

取公钥内容：

```bash
cat ~/.ssh/watchtower_ed25519.pub
```

PowerShell 可用 `Get-Content ~/.ssh/watchtower_ed25519.pub | Set-Clipboard`。

## 先分清两个窗口（最容易粘错的地方）

| 窗口 | 长什么样 | 提示符 | 这里跑什么 |
| --- | --- | --- | --- |
| **OrcaTerm 网页终端** | **浏览器标签页**里的黑色终端，控制台点「登录」打开 | `ubuntu@VM-0-8-ubuntu:~$` | 装公钥、改 sshd、开 ufw、以后装 Nginx —— 所有**服务器上的**命令 |
| **本机 PowerShell / Git Bash** | Windows 上独立的终端程序窗口 | `PS C:\Users\你的用户名>` 或 `~ $` | `ssh-keygen`、`ssh -i ...` 登录验证、测「密码被拒」 —— 所有**从外面连服务器**的命令 |

分不清就在窗口里敲 `hostname`：输出 `VM-0-8-ubuntu` 是服务器，输出你的 Windows 电脑名是本机。

**命令里的 `<公网IP>` 去哪找**：控制台 → 轻量云 → 服务器列表，实例卡片上就写着「公网 IP」，旁边一般有复制按钮；点「登录」弹出的 OrcaTerm 登录框「服务器」一栏里也有。在服务器里敲 `curl -s ifconfig.me && echo` 可以核对。⚠️ 本机 `ipconfig` 看到的是**你自己电脑的局域网 IP**（192.168.x.x / 10.x.x.x），不是服务器公网 IP，别填错；实例重建后 IP 会变，一律以控制台当前显示为准。

⚠️ **`<公网IP>` 是占位符，替换时要把尖括号一起删掉**，只留四段纯数字。报 `hostname contains invalid characters` 基本就是尖括号、中文标点或空格被一起复制进去了（PowerShell 里 `<` 还是保留的重定向符）。最稳的写法是先把 IP 放进变量：

```powershell
$IP = "1.2.3.4"
ssh -i "$env:USERPROFILE\.ssh\watchtower_ed25519" "ubuntu@$IP"
```

只改第一行那串数字，其余原样复制。

> **保命三条里「旧窗口别关」指的是 OrcaTerm 那个浏览器标签页**：改 sshd 期间它要保持登录状态，配置改坏了能立刻从里面改回来。

## 2. 把公钥装到服务器，先验证密钥登录能通

在 **OrcaTerm 网页终端**里（当前用户 `ubuntu`）：

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
KEY="ssh-ed25519 AAAA...换成你的公钥整行... watchtower-admin"
grep -qF "$KEY" ~/.ssh/authorized_keys 2>/dev/null || echo "$KEY" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
wc -l ~/.ssh/authorized_keys
```

> `>>` 是**追加**：同一段命令跑两遍就会写进两行。上面先 `grep -qF` 查重再写，属于**幂等**写法——跑几次结果都一样，`wc -l` 始终是 `1`。部署脚本里到处都要这个习惯，否则重装一次配置就多一份、排错时根本看不出是哪来的。

> 那两个 `chmod` 不能省：sshd 默认开 `StrictModes`，`.ssh` 目录或 `authorized_keys` 若对同组／其他人可写、或属主不是该用户，sshd 会**直接忽略整个文件**，表现是「公钥明明贴进去了却还是要密码」。这是密钥登录最常见的坑。
>
> 另外：公钥写进**谁的** `~/.ssh/authorized_keys`，就是给**谁**开门——`ubuntu`、`deploy`、`root` 各有各的名单，互不相通。所以第 3 步给 `deploy` 复制一份是必要动作，不是多余。删掉名单里那一行 = 立刻吊销这把钥匙，不用改密码、不用重启服务。

**回到自己电脑，开一个新终端**（旧窗口别关）：

```powershell
$IP = "1.2.3.4"
ssh -i "$env:USERPROFILE\.ssh\watchtower_ed25519" "ubuntu@$IP"
```

首次连接会问 `Are you sure you want to continue connecting (yes/no/[fingerprint])?` → 输完整单词 **`yes`**。这一步是把**服务器主机公钥的指纹**记进本机 `known_hosts`，以后每次连接都比对，用来防中间人伪装成你的服务器。想验真，在 OrcaTerm 里敲 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`，指纹应与屏幕上显示的 `SHA256:...` 一致。

之后应看到 `Warning: Permanently added ... to the list of known hosts.` 并直接落到 `ubuntu@VM-0-8-ubuntu:~$`。**私钥没设口令、公钥已装好，正常情况下不应该再要密码**；若出现密码提示或 `Permission denied (publickey)`，先停下来查权限（StrictModes）和公钥内容，别往下走。

> 以后哪天看到 `REMOTE HOST IDENTIFICATION HAS CHANGED`，别无脑删 `known_hosts`——先确认是不是重装过系统／换过实例，那也可能是真的中间人告警。

> **先别用左侧菜单的「SSH 密钥」去绑定**：轻量云绑定密钥会改写实例登录配置、有时要求重启，可控性不如自己写 `authorized_keys`。等全套验收完再考虑托管。

## 3. 建一个跑服务的专用账号 `deploy`

`ubuntu` 已经是非 root 了，但它是**登录/管理账号**。再分出一个只跑服务的账号，好处是：服务被打穿时损失圈在 `/home/deploy` 里，也不会因为误操作把管理账号的家目录搞乱。

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
sudo install -m 600 -o deploy -g deploy ~/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
```

`--disabled-password` 表示这个账号没有密码，只能钥匙进门；`install` 一次把属主和权限都设对，比 `cp + chown + chmod` 三步更不容易漏。

**注意：不要给 `deploy` 加 sudo 组。** 服务账号一旦能提权，前面做的隔离就白费了。以后装软件、改 systemd 单元、改 Nginx 配置都用管理号 `ubuntu` 做；`deploy` 只用来跑应用进程。这是「最小权限」真正落地的地方。

验证（在自己电脑新终端）：

```bash
ssh -i ~/.ssh/watchtower_ed25519 deploy@<公网IP>
id deploy
```

Ubuntu 24.04 实测输出是 `uid=1003(deploy) gid=1003(deploy) groups=1003(deploy),100(users)`：会多一个 `users` 普通补充组，这是 `adduser` 的默认行为，**不影响结论**。判据只有一条——**`groups` 里没有 `sudo`**。想更硬地验证「到底能不能提权」，在服务器里跑 `sudo -l -U deploy`，应输出 `User deploy is not allowed to run sudo ...`。

## 4. 禁密码登录、禁 root 登录

**先备份，再改，再校验。** 用 `sed` 精确匹配行首，避免手滑改错行：

```bash
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak
sudo cp /etc/ssh/sshd_config.d/50-cloud-init.conf /etc/ssh/sshd_config.d/50-cloud-init.conf.bak

sudo sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf
```

再显式补上两条保险（主配置末尾追加即可）：

```bash
grep -qxF 'PubkeyAuthentication yes' /etc/ssh/sshd_config || printf '\nPubkeyAuthentication yes\n' | sudo tee -a /etc/ssh/sshd_config
grep -qxF 'KbdInteractiveAuthentication no' /etc/ssh/sshd_config || printf 'KbdInteractiveAuthentication no\n' | sudo tee -a /etc/ssh/sshd_config
```

**语法校验，绝对不能跳：**

```bash
sudo sshd -t && echo CONFIG_OK
```

只有输出 `CONFIG_OK` 才继续。

**看真正生效的值，这步比 grep 靠谱：**

```bash
sudo sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin|pubkeyauthentication|kbdinteractiveauthentication)'
```

期望是：

```
passwordauthentication no
permitrootlogin no
pubkeyauthentication yes
kbdinteractiveauthentication no
```

只要有一项是 `yes`，说明还有别处覆盖，别往下走，把输出发我。

生效（Ubuntu 服务名是 `ssh`）：

```bash
sudo systemctl daemon-reload
sudo systemctl reload ssh 2>/dev/null || sudo systemctl restart ssh
```

> Ubuntu 24.04 部分镜像启用了 **ssh.socket 按需激活**，新连接会重新读配置。`reload` 之后靠下面的真实登录测试来确认，比纠结服务名可靠。

**从自己电脑做双向验证**（旧窗口仍然别关）：

```bash
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password deploy@<公网IP>
```

应被拒：`Permission denied (publickey)`。然后确认钥匙还进得去：

```bash
ssh -i ~/.ssh/watchtower_ed25519 deploy@<公网IP>
```

再确认 root 被拒：

```bash
ssh -i ~/.ssh/watchtower_ed25519 root@<公网IP>
```

## 5. 防火墙：两层都要配

**第一层 · 控制台**：轻量云 → 服务器 → **点实例名进详情页** → 「**防火墙**」标签，最终只保留 22 / 80 / 443 三条 TCP 允许。

**11-15 实测初始状态**（共 5 条，策略全是「允许」）：

| 应用类型 | 来源 | 协议 | 端口 | 处置 |
| --- | --- | --- | --- | --- |
| 自定义 | 全部 IPv4 | TCP | 8080 | **暂缓删除**，实测有 nginx 在监听（见下） |
| 自定义 | 全部 IPv6 | TCP | 8080 | **暂缓删除**，实例 IPv6 未开启、规则空转，但先别动 |
| Linux 登录(22) | 全部 IPv4 | TCP | 22 | **保留，绝对别碰**，删了 SSH 当场断 |
| HTTP (80) | 全部 IPv4 | TCP | 80 | **保留**，申请 HTTPS 证书要用 |
| Ping | 全部 IPv4 | ICMP | ALL | **保留**，见下方说明 |

**11-15 二次实测（`sudo ss -tlnp | grep ':8080'`）**：

```
LISTEN 0 511 0.0.0.0:8080 0.0.0.0:* users:(("nginx",pid=959,fd=5),...)
```

这台镜像**预装并运行着 nginx，监听 `0.0.0.0:8080`（对外）**，不是只听 localhost。所以删掉外层 8080 规则**会切断外部对该站点的访问**。

**修正后的方案：今天只补 443/tcp，8080 两条先不动。** 等部署篇把 nginx 正式配到 80/443、确认没有站点依赖 8080，再回来删这两条。

> **`0.0.0.0` vs `127.0.0.1`**：前者监听所有网卡、外部能连；后者只本机回环。`localhost` 访问不走网卡，云防火墙和 ufw 都管不到；但**绑在 `0.0.0.0` 的服务同时也对外开着**，删规则确实会影响外部访问。删任何规则前先 `sudo ss -tlnp` 查监听，别凭「应该没人用」——这次就是靠这条命令拦下一次误删。

> 顺带一个好消息：nginx 已经装好并在跑，部署篇省掉安装步骤，只需改站点配置。

**11-15 三次实测（查清这个 nginx）**：

```
sudo ss -tlnp | grep -E ':(80|443|8080)[[:space:]]'
→ 0.0.0.0:80 / 0.0.0.0:8080 / [::]:80  都是 nginx（pid 957/958/959）；443 无人监听
curl -s -I http://127.0.0.1:8080/
→ HTTP/1.1 200 OK, Server: nginx/1.24.0 (Ubuntu), Content-Length: 290
ls -l /etc/nginx/sites-enabled/
→ 只有 default -> /etc/nginx/sites-available/default
```

结论：**80 和 8080 是同一个 nginx、同一个 `default` 默认站点的两个监听口**，内容是那份 290 字节的小页面；没有其它站点、没有真实业务；443 空着符合预期（HTTPS 还没配）。所以关掉 8080 那道门，外部走 80 仍看得到同一份内容，**不会丢网站**。

但**方案维持暂缓删除**：部署篇本来就要改写这份 `default` 配置（去掉 8080 的 listen、加上 443 ssl），到时候连同防火墙规则一起收口，不必现在删一次、过两天又动一遍。可用 `sudo grep -n 'listen\|server_name\|root' /etc/nginx/sites-enabled/default` 坐实「同一站点两个门」。

**11-15 四次实测（补完 443 后的规则列表，共 6 条，策略全为「允许」）**：

| 应用类型 | 来源 | 协议 | 端口 | 处置 |
| --- | --- | --- | --- | --- |
| HTTPS (443) | 全部 IPv4 | TCP | 443 | **本次新增** |
| 自定义 | 全部 IPv4 | TCP | 8080 | 暂缓删除 |
| 自定义 | 全部 IPv6 | TCP | 8080 | 暂缓删除 |
| Linux 登录(22) | 全部 IPv4 | TCP | 22 | 保留，绝对别碰 |
| HTTP (80) | 全部 IPv4 | TCP | 80 | 保留 |
| Ping | 全部 IPv4 | ICMP | ALL | 保留 |

这是**过渡态，不是最终态**。最终只留 22 / 80 / 443 三条 TCP 允许；8080 两条等部署篇改写 nginx `default` 时一起收口。补完规则后**已于 11-15 22:49 从本机 SSH 重登验证通过**（`deploy@VM-0-8-ubuntu:~$`，无密码提示），22 未被误伤，控制台这一层验收完成；另外「端口放通 ≠ 有服务在听」，此时访问 `https://` 依然会失败，因为 443 上还没有程序监听（`ss` 已证实），不是配错了。

> 三个实测坑：① 顶部「**一键放通**」别点，它会一次性放开所有端口；② 「设置多台实例的防火墙?」那个链接通向**防火墙模板**，不是这台实例生效的规则；③ `Ping` 那行端口写着 `ALL`，但协议是 **ICMP**、只用于探测主机是否在线，**不是 TCP/UDP 全端口放行**，别按「删掉所有 ALL 规则」的字面把它误删。

> **关于「22 只放行自己 IP」**：原则上是最小权限，但你的出口 IP 是动态的（登录横幅里 `Last login ... from 222.74.27.136` 只是今天的），写死之后换 WiFi／换网络就连不上，只能靠 TAT 进控制台改回来。现在密码已禁、root 已禁、只剩密钥，22 暴露的攻击面已经很小；**这一轮先放开，等有了固定出口 IP 或做完 HTTPS 再收紧**，别在刚上手时给自己埋一个必踩的锁死坑。

> **别改错地方**：左侧的「**防火墙模板**」是给多台机器套用的模板，不是这台实例生效的规则；轻量云**没有** CVM 那套「安全组」。

**第二层 · 主机内 ufw**（Ubuntu 24.04 通常预装，没有就先 `sudo apt install -y ufw`）：

```bash
sudo ufw status verbose          # 先看现状，通常是 inactive
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp            # 必须排在 enable 之前
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable                  # 出现 "Proceed with operation (y|n)?" 时输 y 回车
sudo ufw status verbose
```

顺序：**先 allow 三条，最后才 enable**。`enable` 会弹一次交互确认，输 `y` 即可，那不是报错。

> **TAT 不受 ufw 影响**：免密连接走云 API + 实例内 agent 主动外连，不需要任何入站端口。所以这一层即使配错，控制台「登录」照样能进去执行 `sudo ufw disable`——第 5 步的风险比第 4 步改 sshd 低。

启用后**从本机 PowerShell 重连一次**，确认 SSH 没被自己挡在外面：

```powershell
$IP = "1.2.3.4"   # 换成控制台上的公网 IP，别把尖括号一起粘进来
ssh -i "$env:USERPROFILE\.ssh\watchtower_ed25519" "deploy@$IP"
```

看到 `deploy@VM-0-8-ubuntu:~$` 才算这层通过。控制台那层是云侧规则、改完立即生效；ufw 是主机内第二层，两层都只留 22/80/443。

**11-16 实测（第一次 `enable` 后）**：`Status: active`、`Default: deny (incoming), allow (outgoing)` 都正确，但 `ufw status verbose` 只列出 `22/tcp` 和 `443/tcp`，**`80/tcp` 缺失**——整块执行时这一行没跑成（粘贴丢行／跳过）。

> 每条 `allow` 出现两行（v4 + v6）是 ufw 默认 `IPV6=yes` 自动同时写的，**不是命令跑了两次**；该实例 IPv6 未开启，v6 那两行空转但不影响。

后果：外层 80 已放通、内层 ufw 拦掉，外部访问 `http://` 会超时；更关键的是 Let's Encrypt 的 **HTTP-01 校验走 80**，缺了它证书申请会失败。补法（在 TAT 里）：

```bash
sudo ufw allow 80/tcp
sudo ufw status verbose
```

补齐后应有 22 / 80 / 443 各两行（v4 + v6），共 6 行。**11-16 18:36 实测已补齐**：`Status: active` 加六行规则，显示顺序为 22 / 443 / 80（v4）与 22 / 443 / 80（v6）——ufw 按**添加先后**排列，规则之间的先后不影响生效，别误以为又是顺序错了。

> 教训：**改完必须逐条对照预期输出**，不能只看 `Status: active` 就以为全部生效。整块粘贴命令丢一行是常见事故，这次靠 `status verbose` 当场抓到。

## 6. 打勾验收

- [x] OrcaTerm 用**免密连接（TAT）**真正进到系统，进去后 `whoami` 输出 `ubuntu`
- [x] `ubuntu` 和 `deploy` 都能用新密钥登录；`id deploy` 显示 **不在 sudo 组**
- [x] `sshd -t` 输出 `CONFIG_OK`
- [x] `sshd -T` 四项全是期望值（密码 no / root no / 公钥 yes / 键盘交互 no）
- [x] 密码登录被拒、root 登录被拒、密钥登录仍可用
- [x] 轻量云**实例详情 → 防火墙**：22 / 80 / 443 / Ping 保留，8080 两条暂缓（**过渡态 6 条**，部署篇再收口）
- [x] `ufw status verbose` 有 22 / 80 / 443 三条（各 v4 + v6 两行，共 6 行），`Default: deny (incoming), allow (outgoing)`
- [ ] 换手机热点另开终端，仍能 SSH 进去（可选，最后再做，验证出口 IP 变化不受影响）

**11-16 18:53 以上 7 项全部实测通过**：`sshd -T` 四项、三向验证、外层 6 条规则、`ufw status verbose` 六行，以及 ufw 启用后**从本机新窗口 SSH 重登成功**。上机加固这一层收口，可以开始部署篇。

## 出事了怎么救

控制台 → 轻量云 → 服务器 → 实例卡片「**登录**」→ OrcaTerm 网页终端（不走公网 SSH，SSH 和防火墙改坏了也进得去），然后：

```bash
sudo cp /etc/ssh/sshd_config.bak /etc/ssh/sshd_config
sudo cp /etc/ssh/sshd_config.d/50-cloud-init.conf.bak /etc/ssh/sshd_config.d/50-cloud-init.conf
sudo systemctl reload ssh
sudo ufw disable
```

这就是为什么第 0 步必须先确认这个入口能用。

## 实测记录（11-12 ~ 11-15）

- **11-15 `sudo ufw status verbose` 实测 `Status: inactive`**：ufw 未启用、连规则列表都没有（名单空白）。误敲 `vervose` 会打印 ufw 完整命令菜单，可当说明书用；只读命令打错不改任何东西。
- **11-15 轻量云控制台防火墙实测共 5 条**：22、80 已放行（印证「能 SSH 登进去就说明外层 22 通」）；**443 默认没有，要手动补**；8080 有 IPv4 / IPv6 两条默认规则；`Ping` 是 ICMP / ALL 而非全 TCP 端口，保留。
- **11-15 重要更正**：曾据「Watchtower 还在本机」推断 8080 没有服务、准备删规则；用户质疑后跑 `sudo ss -tlnp | grep ':8080'`，实测 **nginx 正在 `0.0.0.0:8080` 监听**（pid 957/958/959）。结论改为 **8080 两条暂缓删除**，今天只补 443。教训：文档里的假设和机器实际情况对不上时，以 `ss` 的实测为准；删规则前必查监听。
- **首次密钥登录报 `Connection closed by <IP> port 22`**：TCP 通、握手阶段服务端断开。次日重试自行恢复，判断是云主机首次启动期间 cloud-init / sshd 仍在重载，**不是公钥或权限问题**（那类会报 `Permission denied (publickey)`）。若复现，查 `sudo journalctl -u ssh -u ssh.socket --no-pager -n 40`。
- **PowerShell 出现 `>>` 续行提示**：命令未闭合，此刻根本没连出去；按 `Ctrl+C` 退出，用最短一行 `ssh -i ... ubuntu@<IP>` 重试。别一上来叠 `-v` 和管道。
- **11-13 `sshd -T` 实测四项**：`permitrootlogin no` / `pubkeyauthentication yes` / `passwordauthentication no` / `kbdinteractiveauthentication no`，`sshd -t` 输出 `CONFIG_OK`。`tee -a` 回显的那行孤零零的 `PubkeyAuthentication yes` 不是报错，以 `sshd -T` 为准。
- **11-13 三向验证全部通过**：密码方式 → `Permission denied (publickey).`；deploy 密钥 → `deploy@VM-0-8-ubuntu:~$`；root 密钥 → `Permission denied (publickey).`。至此 sshd 侧加固完成。粘贴输出里每行后的 `>>` 只是显示，命令确实执行了。
- **`50-cloud-init.conf` 的坑已实测命中**：该文件里的 `PasswordAuthentication yes` 排在主配置 `Include` 之前，只改主配置不生效，必须一起改。
- **登录横幅里的 `eth0: 10.x.x.x` 是内网地址**，公网 IP 在云侧映射，所以 `ip a` 里看不到控制台显示的那个地址。
- **`Last login ... from x.x.x.x` 是你自己的出口 IP**，以后做日志审计最直观的一条就是看这里有没有陌生地址。
- 有 **5 个标准安全更新**待打：`sudo apt update && sudo apt upgrade -y`。**等本手册验收完再做**——apt 升级 openssh-server 可能改写 `/etc/ssh/sshd_config` 并弹出 conffile 交互提示，正好跟第 4 步改配置撞车。
- 横幅提示 `New release '26.04.1 LTS' available`：**不要执行 `do-release-upgrade`**。跨大版本升级在学习机上极容易搞坏，且实例 12-08 到期，没有重来的时间。

- **2026-11-13 第 4 步实测**：`sudo sshd -t` 输出 `CONFIG_OK`；`sudo sshd -T | grep` 四项为 `permitrootlogin no` / `pubkeyauthentication yes` / `passwordauthentication no` / `kbdinteractiveauthentication no`，全部达标。`tee -a` 会把它写入的内容**回显**到屏幕（输出里那行孤零零的 `PubkeyAuthentication yes`），不是报错；若某一行没回显，多半是 `grep -qxF` 命中了已有配置、跳过了追加，以 `sshd -T` 的结果为准。

## 现在仍然不要做

- 别把**私钥和密码**发到任何聊天窗口（包括这里）。公网 IP 本来就是公开的，自己查来用没问题。
- 别急着装 Nginx、别传 Watchtower。服务目前还是 Flask 自带开发服务器、HTTP 明文、`.env` 里是开发用的设备令牌，传上去等于把「能往数据库写数据的接口」敞开给全网扫。
- 别为了「图方便」开 0.0.0.0 的全端口规则。

## 下一步

这份手册验收通过后，我给部署篇：以 `deploy` 用户跑 venv + Gunicorn、systemd 开机自启与崩溃自愈、Nginx 反代、Let's Encrypt 证书、定时备份与删库恢复演练，采集端改走 HTTPS 并换掉开发用令牌。整套写成可复现文档，实例到期换机器时照着敲就能重建。
