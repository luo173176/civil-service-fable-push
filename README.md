# civil-service-fable-push 🏛️📖

> 每天早上 **9:00**、晚上 **22:00**（北京时间），把一个公共管理研究生水平的概念
> 藏进一篇寓言故事里，推送到你的手机上——
> 读到最后一刻才恍然大悟：**"原来讲的是这个。"**

## 效果示例

摘自 [examples/阿罗不可能定理.md](examples/阿罗不可能定理.md)：

> 三位长辈各写一张字条，两两相比竟转出一个圈；打分不分胜负；一个注定垫底的"祠堂"半路杀出，反而改写了别人家的输赢……直到账本最后一页，谜底才揭晓——**阿罗不可能定理**。

每次推送包含：寓言故事（700-1000 字）→ 概念揭晓 → 概念解释（800-1500 字）→ 隐喻对应表 → 公务员考试视角 → 思考题。

## 功能特性

- **概念库 68 个**：公共政策、公共管理、行政法、经济学、公共选择、博弈论、行为科学，全部研究生水平，含一句话定义、核心要点、考点关联、常见误解与隐喻设计建议（`config/concepts.yaml`）。
- **防重复循环**：随机选未用概念，记录在 `state/used_concepts.json`，用完一轮自动清零重来，且避开上一次的概念。
- **LLM 生成**：支持任意 OpenAI 兼容接口（OpenAI / DeepSeek / 智谱 / Kimi / 通义 / 自建），提示词模板可自由修改（`prompts/story_prompt.md`）。
- **无 Key 兜底**：不配置 `LLM_API_KEY` 时，自动从 `stories/pregenerated/` 预生成库按文件名顺序推送。
- **8 种推送渠道**：Server酱、PushPlus、Bark、Telegram、企业微信、钉钉、飞书、SMTP 邮件，多渠道并行。
- **全自动闭环**：GitHub Actions 定时触发 → 生成 → 推送 → 自动 commit 故事与状态回仓库。

## 别人如何使用（新用户上手）

本项目已设为 **GitHub 模板仓库**，欢迎自用与分发。三种方式任选其一：

### 方式一：Use this template（推荐）

1. 打开仓库首页，点击绿色按钮 **Use this template → Create a new repository**，为自己的仓库起个名字；
2. 得到一个内容相同、提交历史独立的全新仓库；
3. 按下方[五步部署](#五步部署)配置**你自己的** Secrets 并手动触发一次测试；
4. 完成——定时任务、故事生成与推送都运行在你自己的仓库与渠道上，与本仓库数据完全隔离。

### 方式二：Fork

点右上角 **Fork**，之后同样配置 Secrets 并手动测试。两个注意点：

> ⚠️ **Fork 的仓库定时任务默认是禁用的**：必须进 Actions 标签页手动点 **Enable scheduled workflows**，否则每天 9:00 / 22:00 的两个定时推送永远不会触发（手动 Run workflow 不受影响）。
>
> 好处是可以随时 **Sync fork** 同步本仓库的后续更新（例如新增概念、脚本修复）。

### 方式三：Clone 到本地运行

```bash
git clone https://github.com/luo173176/civil-service-fable-push.git
cd civil-service-fable-push
pip install -r requirements.txt
cp .env.example .env      # 填入你自己的 LLM key 与推送渠道密钥
python scripts/main.py    # 手动运行一次
```

需要定时就在本机用任务计划（Windows）或 crontab（Linux/macOS）调用 `python scripts/main.py`。

### 新用户需要准备什么

- 任一家 OpenAI 兼容服务商的 API Key（服务商与 BASE_URL 对照表见下文[更换 LLM](#更换-llm)）；
- 一个推送渠道的 token（Server酱 / PushPlus 均为微信扫码注册即得）；
- **无需修改任何代码**——概念库、提示词、推送逻辑全部现成；想改推送时间、加概念、换模型见下文[自定义](#自定义)。

## 目录结构

```text
civil-service-fable-push/
├── README.md                       # 本文件
├── requirements.txt                # Python 依赖
├── .env.example                    # 本地环境变量模板（复制为 .env 使用）
├── .gitignore                      # 排除 .env、日志等
├── .github/
│   └── workflows/
│       └── push.yml                # 定时任务：北京时间 09:00 / 22:00
├── config/
│   ├── concepts.yaml               # 概念库（68 个概念）
│   └── settings.example.yaml       # 可选配置模板（复制为 settings.yaml 生效）
├── prompts/
│   └── story_prompt.md             # 故事生成提示词模板
├── scripts/
│   ├── main.py                     # 入口：选概念→生成→保存→推送→记状态
│   ├── llm.py                      # OpenAI 兼容接口封装与输出校验
│   ├── push.py                     # 8 种渠道推送与 Markdown 格式适配
│   ├── concepts.py                 # 概念库加载、校验、随机选取、状态读写
│   └── utils.py                    # 日志、北京时间、文本变换、分段、重试
├── stories/
│   ├── pregenerated/               # 预生成故事库（无 LLM Key 时的兜底）
│   └── （每日生成的故事按 YYYY-MM-DD-HH-概念名.md 存放）
├── state/
│   └── used_concepts.json          # 已用概念与推送历史
├── examples/
│   └── 阿罗不可能定理.md            # 一篇完整的示例故事
└── logs/                           # 本地运行日志（不入库）
```

## 工作原理

每次运行依次执行：

1. **选概念**：从 `config/concepts.yaml` 随机取一个未使用的概念（也可 `--concept` 指定）；
2. **生成故事**：调用 LLM 按 `prompts/story_prompt.md` 生成（前 85% 左右纯故事不剧透，结尾揭晓概念并解释）；无 Key 则取预生成库；
3. **保存**：写入 `stories/YYYY-MM-DD-HH-概念名.md`（北京时间）；
4. **推送**：向 `PUSH_CHANNEL` 指定的所有渠道推送 Markdown（各渠道自动做格式适配与分段）；
5. **记录状态**：更新 `state/used_concepts.json`，由 GitHub Actions 自动 commit 回仓库。

## 五步部署

### 第 1 步：创建 GitHub 仓库并上传代码

在 [github.com/new](https://github.com/new) 新建一个仓库（Public 或 Private 均可），然后：

```bash
cd civil-service-fable-push
git init -b main
git add .
git commit -m "init: 公务员寓言每日推送"
git remote add origin https://github.com/<你的用户名>/civil-service-fable-push.git
git push -u origin main
```

或者用 GitHub CLI 一条龙：`gh repo create civil-service-fable-push --private --source=. --push`。

> 网络环境访问 GitHub 不稳定时，可用 SSH over 443：在 `~/.ssh/config` 中配置
> `Host github.com` → `HostName ssh.github.com` → `Port 443`，再以 `git@github.com:...` 推送。

### 第 2 步：配置 Secrets

仓库页面 → **Settings → Secrets and variables → Actions → New repository secret**，按需添加：

| Secret | 必填 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 有 LLM 就必填 | OpenAI 兼容接口的 Key |
| `LLM_BASE_URL` | 可选 | 默认 `https://api.openai.com/v1` |
| `LLM_MODEL` | 可选 | 默认 `deepseek-chat` |
| `LLM_TEMPERATURE` | 可选 | 默认 `0.8` |
| `PUSH_CHANNEL` | 必填 | 渠道名，逗号分隔多选 |
| `SERVERCHAN_SENDKEY` | 用 Server酱 时填 | [sct.ftqq.com](https://sct.ftqq.com) 获取 |
| `PUSHPLUS_TOKEN` | 用 PushPlus 时填 | [pushplus.plus](https://www.pushplus.plus) 获取 |
| `BARK_URL` | 用 Bark 时填 | 形如 `https://api.day.app/你的DeviceKey` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 用 Telegram 时填 | BotFather 建 Bot；`@userinfobot` 查 chat_id |
| `WECOM_WEBHOOK` | 用企业微信时填 | 群机器人 Webhook 地址 |
| `DINGTALK_WEBHOOK` | 用钉钉时填 | 安全设置选**自定义关键词**（推荐关键词：寓言） |
| `FEISHU_WEBHOOK` | 用飞书时填 | 群自定义机器人 Webhook 地址 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `MAIL_TO` | 用邮件时填 | 465 走 SSL，587 走 STARTTLS；`SMTP_PASS` 是授权码 |

最省事的组合：`LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL` + `PUSH_CHANNEL=serverchan` + `SERVERCHAN_SENDKEY`，共 5 个。

### 第 3 步：确认 Actions 已启用

仓库顶部 **Actions** 标签页：若出现提示，点击 **I understand my workflows, go ahead and enable them**。确认左侧能看到"每日寓言推送"工作流。私有仓库默认每月有 2000 分钟免费额度，本项目每天约消耗 2 分钟，绰绰有余。

### 第 4 步：手动触发一次测试

**Actions → 每日寓言推送 → Run workflow → Run workflow**，然后点进运行日志，依次检查：

- "本次概念：xxx" 出现在日志中；
- 每个已配置渠道打印"推送成功"或"跳过（缺环境变量）"；
- 手机上收到推送；
- 仓库 `stories/` 多了一个新文件，`state/used_concepts.json` 更新，Actions 自动产生一个 commit。

### 第 5 步：放手自动运行

测试通过后无需任何操作，每天北京时间 9:00 与 22:00 自动推送（受 GitHub 平台调度影响可能延迟，见下文注意事项）。想跳过等待可随时手动 Run workflow。

## 本地运行

```bash
cd civil-service-fable-push

# 1. 安装依赖（建议虚拟环境）
python -m venv .venv
source .venv/bin/activate          # Windows Git Bash: source .venv/Scripts/activate
pip install -r requirements.txt

# 2. 配置环境变量（或直接使用系统环境变量）
cp .env.example .env               # 填入 LLM_API_KEY 与推送渠道密钥

# 3. 运行
python scripts/main.py                            # 完整流程
python scripts/main.py --dry-run                  # 只生成保存，不推送、不写状态
python scripts/main.py --concept arrow-impossibility  # 指定概念
python scripts/main.py --list-concepts            # 查看概念库
```

## 自定义

### 修改推送时间

默认每天北京时间 **09:00** 与 **22:00** 各推送一次。为了绕开 GitHub 定时调度在整点的高延迟（可晚数十分钟甚至数小时），工作流改为**每 15 分钟触发一次**，由脚本判断当前是否处于推送档期窗口（档期后默认 120 分钟内）：窗口外秒级退出，不调用 LLM、不产生提交；窗口内且当日该档尚未推送，才执行真正的生成与推送。实际推送通常落在档期后 15-30 分钟内。

- **改档期时间**：新增 Secret `SLOT_TIMES`，填北京时间、逗号分隔，如 `08:30,21:30`；
- **改窗口时长**：Secret `SLOT_WINDOW_MINUTES`（默认 120）；
- 手动 Run workflow **不受档期限制**，随时可加推一篇；
- 想分钟级准点：可在 cron-job.org 等免费定时服务配置北京时间 9:00 / 22:00 调用本仓库的 workflow_dispatch API（创建一个仅 `workflow` 权限的 fine-grained token 即可）。

### 添加概念

编辑 `config/concepts.yaml`，照抄现有字段结构新增一段即可，`id` 必须唯一：

```yaml
- id: your-concept-id
  name: 概念名
  discipline: 学科
  difficulty: 进阶            # 基础 / 进阶 / 研究生
  one_liner: 一句话定义。
  key_points:
    - 要点一
    - 要点二
    - 要点三
  exam_relevance: 考试关联。
  misconception: 常见误解。
  metaphor_hint: 隐喻设计建议。
```

### 更换 LLM

改两个 Secrets 即可（`LLM_BASE_URL` + `LLM_MODEL`），任何 OpenAI 兼容接口都行：

| 服务商 | BASE_URL | 模型示例 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| 月之暗面 | `https://api.moonshot.cn/v1` | `moonshot-v1-32k` |
| 阿里通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |

生成风格与结构由 `prompts/story_prompt.md` 控制，可自由修改（保留 `{{字段}}` 占位符）。

### 更换 / 新增推送渠道

改 `PUSH_CHANNEL` 即可，可选值：`serverchan`、`pushplus`、`bark`、`telegram`、`wecom`、`dingtalk`、`feishu`、`mail`，逗号分隔可同时多渠道。各渠道格式适配已内置：Telegram 自动转 HTML 并分段、企业微信/钉钉/飞书自动把表格降级为文本、邮件自动转 HTML。

两个渠道有特殊说明：**Bark** 对长文本支持有限，只推送前 1000 字摘要（完整内容看仓库）；**钉钉**自定义机器人需要安全设置，请选"自定义关键词"（推荐关键词：寓言），本项目的加签方式暂不支持。

### 不用 LLM：预生成库

把写好的故事放进 `stories/pregenerated/`（可先复制 `examples/` 下的文件），程序会按文件名顺序逐日推送，并在状态文件中记录进度。适合想完全人工把关内容质量的用法。

## 注意事项

1. **定时与延迟**：GitHub Actions 的 `schedule` 是尽力而为调度。本项目用"每 15 分钟触发 + 档期窗口判断"绕开整点拥堵——正常情况下推送落在档期后 15-30 分钟，极端拥堵也不会晚于窗口上限（默认 2 小时）；LLM 生成失败时会自动带纠错信息重试，仍失败则转投预生成库兜底。
2. **60 天不活跃会被暂停**：仓库连续 60 天没有任何 push，GitHub 会自动停用定时任务并发邮件提醒；本项目每天自动 commit，通常不会触发。若真被停用，去 Actions 页面手动重新 Enable 即可。
3. **时区换算**：GitHub cron 只认 UTC；北京为 UTC+8 且无夏令时，两者恒差 8 小时（北京 09:00 = UTC 01:00，北京 22:00 = UTC 14:00）。
4. **密钥安全**：密钥只放 GitHub Secrets 或本地 `.env`（已被 `.gitignore` 排除），不要写进代码、README 或 issue。
5. **LLM 输出波动**：程序会校验输出必须包含全部六个章节、故事部分字数在要求区间内（严重超出 1000 字上限或不足会自动重试生成）；如某天生成最终失败，当天不会推送，次日恢复（也可手动重跑）。
6. **推送长度**：Telegram、企业微信会自动按渠道上限分段；Bark 只推摘要。

## 常见问题（FAQ）

- **到点没运行？** Actions 页应能看到每 15 分钟一次的运行记录（窗口外的运行秒级结束、显示 success 属正常现象，日志为"不处于任何推送档期窗口"）；若档期后两小时仍未收到推送，点开最近一次 schedule 运行看日志。
- **运行成功但没收到推送？** 查看日志中每个渠道的结果行：`skipped` 说明对应 Secret 没配，`failed` 会带具体错误；多渠道逗号分隔时注意不要带空格（带空格也能容忍，但建议规范）。
- **报错"预生成库为空"？** 没配 `LLM_API_KEY` 且 `stories/pregenerated/` 里没有故事——二选一解决。
- **查已推送过哪些概念？** 看 `state/used_concepts.json` 的 `history` 字段。
- **想重新开始一轮循环？** 把 `state/used_concepts.json` 中的 `used_ids` 清空为 `[]` 即可。
- **手动触发也失败了？** 常见原因：概念库 YAML 缩进错误（日志会指明哪个概念缺哪个字段）、LLM Key 余额不足或 `LLM_BASE_URL` 填错。
