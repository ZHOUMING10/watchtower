# 02 · 把 Watchtower 部署上云

> 前置：`deploy/01-secure-the-host.md` 第 6 节 7 项已于 11-16 全部实测通过。
> 本文按小步推进：每步先讲「为什么」再动手，每步都有可执行验证。
> 服务器命令由用户在 TAT / `deploy` SSH 会话中执行，本文档不代跑、不谎称已验证。

## 现实约束（11-16 查证）

- 实例是**北京地域**的腾讯云轻量应用服务器（大陆节点）：**未备案域名解析到本机，80/443 会被拦截**，HTTPS 也一样。备案需 10–20 工作日，且轻量实例要包年包月累计 ≥3 个月、备案时剩余有效期 ≥1 个月；实例 12-08 到期，此路不走。
- 腾讯云官方规则：**不使用域名解析指向服务器时，不需要备案**。
- Let's Encrypt 自 **2026-01-15** 起正式支持**公网 IP 证书**（IPv4 / IPv6），必须选 `shortlived` profile，有效期 160 小时（约 6.6 天），Certbot 2026-03 起支持；验证方式仅 http-01 / tls-alpn-01，正好用已放行的 80 / 443。
- **结论：HTTPS 走 IP 证书，不买域名、不备案。** 代价是必须做自动续期（systemd timer），正好练「服务长期不出事」。备选方案是自签证书（浏览器报警告，但零依赖）。
- 具体 certbot 版本、profile 参数与续期命令，**等走到第 4 步时查证后再写入**，不提前给未验证命令。

## 分四步（一次一步，每步可验证）

| # | 做什么 | 先讲清 | 验收 |
| --- | --- | --- | --- |
| 1 | 代码上传 + 建独立 venv，以 `deploy` 跑起 `/healthz` | 为什么服务器上要「重新造环境」、不能整个目录搬过去；为什么 `.env` 不跟着传 | 服务器内 `curl 127.0.0.1:5000/healthz` 返回 200；外部访问 5000 不通 |
| 2 | Gunicorn 常驻 + systemd 开机自启 | Flask 自带开发服务器为什么不能挂公网；「关掉窗口服务还在吗」 | `systemctl status` active；kill 进程后自动拉起；重启后仍在 |
| 3 | Nginx 反代 80/443 → 127.0.0.1:5000 | 为什么内部端口不对外暴露；`0.0.0.0` vs `127.0.0.1` | 外网 `http://公网IP/` 能开面板；5000 外部连不上；顺带收口 8080 两条 |
| 4 | HTTPS（IP 证书）+ 采集端改造 + 自动续期 | 证书解决什么（和 SSH 密钥不是一回事）；设备令牌为什么必须换 | `https://` 无警告、HTTP 跳转、采集端走 HTTPS 上报成功、续期演练通过 |

顺序不能反过来：**先让程序在服务器内部跑通（1、2），再让 Nginx 对外接客（3），最后上 HTTPS（4）**。任何一步没验就往下走，出问题时分不清是代码错还是服务器配错。

## 第 1 步 · 代码上传（11-18 完成：6 个文件已上传）

### 为什么不能 `scp -r` 整个 `D:\watchtower`

| 文件 | 传不传 | 原因 |
| --- | --- | --- |
| `app.py` / `config.py` / `collector.py` | 传 | 业务代码，跨平台通用 |
| `templates/index.html` / `static/style.css` / `static/app.js` | 传 | 面板前端 |
| `.env.example` | 传 | 当模板，下一步在服务器上**单独**生成 `.env` |
| `.env` | **不传** | 含本机开发用令牌；密钥不跟着代码走，每台机器单独生成 |
| `.venv/` | **不传** | Windows 虚拟环境，Linux 用不了；服务器上要重新建 |
| `*.db` / `logs/` | **不传** | 本机测试数据和日志，服务器从空库开始 |
| `*.bat` / `start*.bat` | **不传** | Windows 启动脚本，Linux 用 systemd |

`config.py` 里 `BASE = Path(__file__).resolve().parent` —— 数据库、日志、`.env` 都写在**代码所在目录**。所以目标目录必须让 `deploy` 可写，用 `/home/deploy/watchtower/`，并且**要用 `deploy` 自己的会话建目录**（用 `ubuntu` 建属主不对，`deploy` 会写不进去）。

默认 `HOST=127.0.0.1`、`PORT=5000`（见 `config.py`），正好符合「只对内、外部不可达」。

### 实测记录（11-18）

动作 A 在 **`deploy` 的 SSH 会话**里执行，最终全部通过：

| 命令 | 实际输出 | 结论 |
| --- | --- | --- |
| `whoami` | `deploy` | 目录由 deploy 自己创建，属主正确 |
| `python3 --version` | `Python 3.12.3` | 有效；**本机是 3.13.14**，版本不同 |
| `mkdir -p ~/watchtower/templates ~/watchtower/static` | 无输出 | 成功，但**实际建成了 `watchower`（`t` 丢了）** |
| `ls` | `watchower` | 目录存在（当时误读为 `watchtower`） |
| `ls -la` | `drwxrwxr-x 4 deploy deploy ... watchower` | 属主 `deploy deploy` ✅、链接数 4 = 两个子目录都在 |
| `mv watchower watchtower` + `ls -la` | `drwxrwxr-x 4 deploy deploy ... watchtower` | 改名成功，名字与文档一致 |

> **服务器 Python 3.12.3 vs 本机 3.13.14**：版本都不一样，这是「`.venv` 是平台相关的、必须在服务器上重建」最直接的实证，比讲道理管用。

**这次真实的坑，两个，叠在一起：**

1. **目录名少了一个 `t`**。`watchtower` = watch + tower，实际建成了 `watchower`。于是后面每一条 `ls -ld watchtower` 都报 `No such file or directory`——**报错完全正确，那个名字确实不存在**。定位靠的是 `ls -la`（不需要输入任何文件名），一眼看到真实名字。
2. **中文输入法吃符号**。`ls -ld ~/watchtower ...` 被敲成 `,ls -ld~watchtower ~watchower/...`（行首多逗号、`~/` 的斜杠消失、整串被引号包住），报 `invalid option -- ','`。

规避规则（以后每次都适用）：

1. 敲命令前按 `Shift` / `Ctrl+Space` **切到英文输入法**。
2. 验证类命令**用相对路径**，别带 `~`、`/`、`,`、引号。当前就在家目录，`ls -ld watchtower` 足够。
3. 一次只粘**一行**；从聊天/网页复制代码块时，先粘到记事本再复制一次，剥掉富文本格式。
4. **建完目录立刻 `ls -la` 核对名字**，比事后逐条命令试便宜得多。
5. 长命令优先写成脚本（本步的 `upload.bat`），把要输入的字符降到最少。

> 下一步预告：Ubuntu 24.04 的 `python3 -m venv` 可能报 `ensurepip is not available`，需要管理号 `ubuntu` 安装 `python3-venv`（`deploy` 无 sudo）。到建 venv 那步先查证再写命令，不提前塞未验证内容。

### 动作 B · 传文件（用脚本，不要手敲）

`D:\watchtower\upload.bat` 已生成：三条 `scp` + 全成功后自动 SSH 登录。**纯 ASCII、无中文**，避免 cmd 编码问题。

用法：在本机 PowerShell 里（先 `exit` 退出服务器会话）——

```powershell
cd D:\watchtower
.\upload.bat
```

或者直接在文件管理器里双击 `upload.bat`。

| 顺序 | 内容 |
| --- | --- |
| 1/3 | `app.py` `config.py` `collector.py` `.env.example` → `~/watchtower/` |
| 2/3 | `templates\index.html` → `~/watchtower/templates/` |
| 3/3 | `static\style.css` `static\app.js` → `~/watchtower/static/` |
| 末尾 | 三步全部成功后自动 `ssh` 登进服务器 |

> 脚本里硬编码了 `deploy@SERVER_IP`。实例重建或换 IP 后改 `set HOST=` 那一行即可。

传完在服务器里验证（**每步单独一行，逐条粘**）：

```bash
ls -lR watchtower
```

期望：三层目录共 6 个文件，属主全 `deploy`，**没有 `.env`、没有 `.venv`、没有 `.db`**。

### 验收清单

- [x] 服务器上 `whoami` 输出 `deploy`
- [x] `python3 --version` 有输出（3.12.3）
- [x] `/home/deploy/watchtower/` 及 `templates/`、`static/` 属主均为 `deploy`（`ls -la` 已确认）
- [x] 目录名已修正为 `watchtower`（原为 `watchower`）
- [x] 目录里只有标「传」的 6 个文件，**没有 `.env`、没有 `.venv`、没有 `.db`**（21:53 `ls -la` 确认 `.env.example` 348 字节在，越界文件均无）
- [x] 上传当时未启动服务、未生成 `.env`、未碰 nginx / 防火墙（venv 与 `.env` 在第 2 步才建）

## 第 2 步 · 运行环境与冒烟验证（11-18 完成）

顺序：建 venv → 装 Flask → 造 `.env` → 启动 → 问 `/healthz` → 停掉。

```bash
cd ~/watchtower
python3 -m venv .venv                       # 成功时无输出
.venv/bin/pip install flask                 # 装进 venv，不是系统 Python
cp .env.example .env
sed -i "s/replace-with-a-long-random-string/$(openssl rand -hex 32)/" .env
chmod 600 .env
.venv/bin/python app.py &                   # 验证用；常驻要靠 systemd
curl -s 127.0.0.1:5000/healthz
kill %1
```

**实测（11-18 22:34–23:02）**

| 检查 | 结果 |
| --- | --- |
| `python3 -m venv .venv` | 无输出成功；`.venv/bin` 有 `pip` / `python3.12` / `activate` → **预判的 `ensurepip is not available` 坑未出现**，无需 `ubuntu` 安装 `python3-venv` |
| `pip install flask` | **Flask 3.1.3** + Werkzeug 3.1.9 / Jinja2 3.1.6 / click 8.5.1 / blinker 1.9.0 / itsdangerous 2.2.0 / MarkupSafe 3.0.4，`pip list` 核对在 venv 内 |
| `.env` | `openssl rand -hex 32` 现场生成令牌 + `chmod 600`；令牌未经过聊天 |
| 令牌生效校验 | `.venv/bin/python -c "import config;print(len(config.DEVICE_TOKEN))"` → **`64`**，排除走 `config.py` 第 26 行 `dev-token-change-me` 兜底 |
| `/healthz` | 两次（22:53、23:02）均 `200`，返回 `{"status":"ok","time":"..."}`，**响应体只有 `status`/`time` 两个字段** |

两个实测坑与说明：

- **`Tip: There are .env files present. Install python-dotenv to use them.` 是噪音**：`config.py` 第 12–24 行 `_load_env()` 手写解析 `.env`，不依赖 python-dotenv，配置确实被读取。看到这行不必安装任何东西。
- **时间字段是 UTC，日志行是本地时区**（JSON `14:53 UTC` 对应日志 `22:53` 北京时间）。采集端跨时区接入时要留意。
- **验证用 `&` 起的进程挂在 SSH 会话上，断线即死**（11-18 22:26 实测过一次 `client_loop: send disconnect: Connection reset`，重连后 `ps -u deploy` 无 python 进程）。这是必须上 systemd 的直接理由。

## 第 3 步 · systemd 常驻与自愈（11-21 开始）

**为什么必须做**：`&` 起的进程父进程是 SSH 会话里的 bash，会话一断（校园网 20 分钟清空闲连接）进程即死。systemd 让 gunicorn 的父进程变成 PID 1，从此与登录会话无关。

### 3.1 装单元

`watchtower.service` 用 `upload.bat` 之外的方式单独传：

```bash
scp deploy\watchtower.service deploy@SERVER_IP:/tmp/
```

服务器上用 `admin.bat`（有 sudo）执行四步：

```bash
sudo mv /tmp/watchtower.service /etc/systemd/system/watchtower.service
sudo chown root:root /etc/systemd/system/watchtower.service
sudo systemctl daemon-reload
sudo systemctl enable --now watchtower
```

四步各自的作用：①挪到系统目录（systemd 只认这三个位置，其中 `/etc/systemd/system/` 优先级最高）②属主必须是 root，普通用户能改的单元文件 systemd 会拒绝执行 ③让 systemd 重读单元文件（**改过 .service 之后不做这步等于没改**）④`enable` 写开机自启清单 + `--now` 立刻启动，一条顶两条。

### 3.2 实测（11-21 10:17）

```
Active: active (running) since Sat 2026-11-21 10:17:35 CST
Main PID: 3766829 (gunicorn)
Tasks: 4  Memory: 44.4M  CPU: 264ms
```

CGroup 下 3 个进程 = 1 master + 2 worker：

| PID | 角色 | 说明 |
| --- | --- | --- |
| 3766829 | master | 不接请求，只负责起/管/补 worker |
| 3766848 | worker | 真正处理 HTTP |
| 3766854 | worker | 真正处理 HTTP（`-w 2` 的第二个） |

两个 worker 的意义：一个卡死或崩掉，另一个继续接客，用户不会立刻看到 500。2 核机器 `-w 2` 合适，开多了只是互相抢 CPU。

日志尾行 `Control socket listening at .../gunicorn.ctl` 是 gunicorn 27 的控制套接字，正常，无需处理；工作目录里会多出 `gunicorn.ctl` 文件。

**跨会话存活实证（11-21 10:17 → 18:45，8h28m）**：期间本机（Windows）**关机一次**、SSH 断连至少两次，`MainPID` 始终为 `3766829` 未变。PID 由内核递增分配，进程若重启过必然拿到更大的新号，**PID 不变即可判定"一次都没死过"**。这是 systemd 与 `&` 的本质差异：前者寿命等于机器寿命，后者上限是一次 SSH 会话。

### 3.3 三个验证（区分开，别混）

| 验证 | 命令 | 说明 |
| --- | --- | --- |
| 应用自身活着 | `curl -s 127.0.0.1:5000/healthz` | 走回环，绕过 nginx，测最内层 |
| 开机自启清单 | `systemctl is-enabled watchtower` | `enabled` = 写进清单了，**不等于**验证过 |
| 此刻在跑 | `systemctl is-active watchtower` | 与上一条独立：可 enabled 但 inactive |
| 断线不死 | `exit` 后重连再查 | systemd 带来的核心改变 |

### 3.4 自愈演练

```bash
systemctl show -p MainPID --value watchtower    # 取当前 PID，别抄旧值
sudo kill -9 <PID>
sleep 5
systemctl status watchtower --no-pager -l       # 看 MainPID 是否变、有无 restart counter
journalctl -u watchtower -n 30 --no-pager
```

`Restart=always` + `RestartSec=3` 的效果：任何原因的退出都 3 秒后重拉，日志留 `Main process exited, code=killed, status=9/KILL` 与 `Scheduled restart job, restart counter is at 1`。

**实测（11-21 18:47）**

| 项 | 杀之前 | 杀之后 |
| --- | --- | --- |
| Main PID | 3766829 | **3885715** |
| Active since | 10:17:35 | **18:47:26** |
| Tasks | 4 | 4（master + 2 worker 全恢复） |
| Memory | 44.4M | 44.3M |

**`1s ago` 这个读数是 `RestartSec=3` 的直接证据**，可用来验算：`kill` 在 T 时刻，systemd 等满 3 秒于 T+3 拉起，`sleep 5` 后于 T+5 执行 `status` → 只见 `1s ago` 而非 `5s ago`。差的这 3 秒就是刻意留的缓冲。

**为什么必须留缓冲**：若代码有立即崩溃的 bug（如语法错），无延迟重启会变成一秒内反复起崩，CPU 与日志被瞬间打满。3 秒间隔把启动频率压住，留出登录改代码的窗口。

**必须知道的边界**：10 秒内连续重启 5 次以上会触发 `start-limit-hit`，单元被标记 `failed` 并**停止重试**，需 `systemctl reset-failed watchtower` 清计数。即 **systemd 只能救进程，救不了业务**——代码有 bug 时表现为反复重启→最终放弃。

### 3.5 重启自启验证（最后一道，`is-enabled` 无法替代）

`enable` 只是把单元写进 `multi-user.target` 的待办清单，**清单会不会被执行，只有真重启才知道**。

```bash
sudo reboot          # SSH 立即断开，属正常，不是故障
# 等满 60 秒（2核机器启动+拉起几十个单元需时间，太早连会 Connection refused）
# 重连后：
uptime -s
systemctl is-active watchtower
curl -s 127.0.0.1:5000/healthz
```

**实测（11-21 18:51:42 发指令 → 18:51:51 起来）**

| 检查 | 输出 | 判定 |
| --- | --- | --- |
| `uptime -s` | `2026-11-21 18:51:51` | 机器确已重启（指令到关机实际完成间隔 9 秒） |
| `systemctl is-active` | `active` | **登录后未做任何操作**，服务自启成功 |
| `/healthz` | `{"status":"ok","time":"2026-11-21T10:55:24.295655+00:00"}` | 应用层应答正常；`time` 为 UTC，对应北京时间 18:55:24 |

到这一步，「关机 → 开机 → 服务自动恢复」闭环完成，**不需要任何人记得去启动它**。

**顺带的分界线：服务起来 ≠ 数据还在。** 前者是进程层（systemd 负责），后者是存储层（取决于文件在哪个分区）。本项目 `config.py:38` 为 `DB_PATH = BASE / "watchtower.db"`，即 `/home/deploy/watchtower/watchtower.db`，普通磁盘文件，重启不动它。若写成 `/tmp/watchtower.db`，重启即清空，而服务照样健康起来、静默新建一个空库——**健康检查是绿的，业务数据是空的**，属最隐蔽的一类事故。以后每加一处存储都要自问：重启后这个文件还在吗。

### 3.6 日常操作对照

| 目的 | 命令 |
| --- | --- |
| 重启服务（改代码后） | `sudo systemctl restart watchtower` |
| 停止（真不想让它跑） | `sudo systemctl stop watchtower` |
| 取消开机自启 | `sudo systemctl disable watchtower` |
| 改过 .service 后 | `sudo systemctl daemon-reload && sudo systemctl restart watchtower` |
| 看实时日志 | `journalctl -u watchtower -f` |

## 第 3 步完成判定

| # | 条件 | 状态 |
| --- | --- | --- |
| 1 | 单元在 `/etc/systemd/system/`，属主 root | 完成 |
| 2 | `is-enabled` = `enabled`、`is-active` = `active` | 完成 |
| 3 | 跨会话存活：本机关机 + SSH 断连 8h28m，PID 未变 | 完成 |
| 4 | 自愈：`kill -9` 后 3 秒复活，PID 更新，`restart counter` 记账 | 完成（3766829 → 3885715） |
| 5 | 重启自启：`reboot` 后无需登录即恢复，`/healthz` 正常 | 完成（18:51:51 起） |

**至此不再有"手动起服务"这个动作。** 唯一还剩的手动项：改代码后要 `sudo systemctl restart watchtower`。

## 第 4 步 · 反向代理（11-23 完成：公网已能打开面板）

### 4.1 起点状态（和标准 Ubuntu 不一样）

| 项 | 实际 |
| --- | --- |
| nginx 版本 | 1.24.0 (Ubuntu) |
| `sites-enabled` | 只有 `default`（腾讯云改过的占位页，标题是「我的服务器」） |
| 监听 | `default` 同时占用 `0.0.0.0:8080` **和** `0.0.0.0:80`，443 无人监听 |
| `conf.d/` | 另有 `myapp.conf`（93 字节）也 `listen 8080` |

**所以这一步不是「新增站点」，是把 `default` 换掉。**

### 4.2 五条动作

```bash
# 0) 保底：先备份原配置
sudo cp -a /etc/nginx/sites-available/default /etc/nginx/default.bak-20261121

# 1) 装配置、停用默认站点
sudo mv /tmp/watchtower.nginx.conf /etc/nginx/sites-available/watchtower
sudo chown root:root /etc/nginx/sites-available/watchtower
sudo rm /etc/nginx/sites-enabled/default
sudo ln -s /etc/nginx/sites-available/watchtower /etc/nginx/sites-enabled/watchtower

# 2) 闸门
sudo nginx -t

# 3) 生效
sudo systemctl reload nginx

# 4) 验证（看内容，不只看状态码）
curl -s http://127.0.0.1/ | grep -i "<title>"
```

`sites-available` 是仓库（放着不生效），`sites-enabled` 是生效区（只放软链接）。删软链接 = 停用，文件本身还在，所以换掉是安全的。

### 4.3 三个必须记住的坑（都是实际踩过的）

**坑 1 · 状态码 200 不等于东西对了**

腾讯云占位页和你的面板**都是 `200 OK`**。只 `curl -o /dev/null -w %{http_code}` 会得到"一切正常"的假信号。必须比对内容：

```bash
curl -s http://127.0.0.1/ | grep -i "<title>"
```

`200` + 有标题 + 完整 HTML，仍可能是错的页面。这就是监控里"内容校验"存在的理由。

**坑 2 · `reload` 之后不能立刻测**

`reload` 是渐进式的：master 读新配置 → 起新 worker → 通知旧 worker"手上活干完就下班"。旧 worker 在这段时间里**仍按老配置应答**。reload 后立刻 curl，很可能打到旧 worker，被误判成"配置没写对"。

正确的验证顺序：

```bash
sudo systemctl reload nginx
sudo ss -tlnp | grep 8080        # 看内核事实，不看配置、不看一次 curl
```

**配置是"应该怎样"，`ss` 是"实际怎样"，两者冲突时永远信 `ss`。**

**坑 3 · 换掉 `default` 之后占位页还在**

因为占位页不是 `sites-enabled/default` 发的，是 `conf.d/myapp.conf` 发的（`listen 8080; server_name _; root /var/www/html`）。排查办法是让 nginx 自己交代它加载了什么：

```bash
sudo nginx -T 2>/dev/null | grep -E "configuration file|listen |server_name |proxy_pass"
```

`nginx -T`（大写）打印**实际加载的完整配置**并标注来源文件，是 nginx 排查第一神器。

### 4.4 8080 收口

```bash
sudo cp -a /etc/nginx/sites-available/watchtower /etc/nginx/watchtower.bak-20261123
sudo sed -i '/listen 8080;/d' /etc/nginx/sites-available/watchtower
grep -n "listen" /etc/nginx/sites-available/watchtower    # 应只剩两行 80

sudo mv /etc/nginx/conf.d/myapp.conf /etc/nginx/myapp.conf.disabled   # 移走不删

sudo nginx -t && sudo systemctl reload nginx
curl -s http://127.0.0.1/ | grep -i "<title>"                          # 仍是面板
curl -s -o /dev/null -w "8080: %{http_code}\n" http://127.0.0.1:8080/  # 000 = 连不上
```

验收实测（11-23 22:0x）：`sudo ss -tlnp | grep 8080` **无输出**，8080 从内核层面确实空了。

### 4.5 验收结果

浏览器打开 `http://SERVER_IP`（不带端口）—— **面板正常显示**。整条链路：

```
公网 → 云防火墙(80) → ufw(80) → nginx:80 → 127.0.0.1:5000(gunicorn) → Flask → SQLite
```

这是这个项目第一次成为「别人能打开的东西」。

**但注意：能在浏览器打开 ≠ 数据是活的。** 打开时面板显示「设备离线」、温度 `--`、最近读数「等待数据」，说明 `/api/ingest` 这条**写路径**从未成功落过一条数据（采集端默认打 `127.0.0.1:5000`，在笔记本上跑只会打到笔记本自己）。读路径通了、写路径还是空的 —— 这是第 5 步要解决的。

### 4.6 安全现状（必须知道）

- 面板 `/` **没有任何鉴权**，任何拿到 IP 的人都能看设备和温度数据。
- 写接口 `/api/ingest` 有 `X-Device-Token` 保护，无令牌写不进去。
- 当前数据不敏感，可接受；一旦接真实场景，面板前面必须加一层密码（或至少上 HTTPS + 限流）。

## 下一步 · 第 5 步（两件事，顺序可换）

1. **让写路径通**：在服务器上把 `collector.py` 跑成**第二个 systemd 服务**（练第二个 unit、多服务托管），或在笔记本上设 `WATCHTOWER_URL=http://SERVER_IP/api/ingest` 从公网打（顺带验证令牌鉴权会拦住错误令牌 → 401）
2. **HTTPS**：Let's Encrypt 已支持给**公网 IP** 签证书（`shortlived` profile，约 6 天有效、需自动续期），可绕开"未备案域名不能解析到 80/443"的限制

## 现在不做

- 不删外层 8080 两条（**已完成于 11-23**：8080 在内核层已无人监听，云防火墙那两条可随时删，删前先确认浏览器仍走 80）
- 不打那批安全更新（11-18 横幅已到 **13** 个，单独时段做，做完复查 `sshd -T` 四项 + 重登）
- 不执行 `do-release-upgrade`（跨大版本升级极易搞坏，且实例 12-08 到期）
- 不引入 Docker / K8s / 微服务
