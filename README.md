# Yukino 0.8

一个可以导入世界观、人物与开场，自由推进故事的浏览器 AI 视觉小说原型。

**Yukino** 是暂定项目名，**0.8** 是本次公共壳版本；底层舞台版本为 **4.7**。项目运行在本机 Python 服务和浏览器中。文本由 DeepSeek Flash 生成，动态图片由已登录的 Codex CLI 原生生图服务生成，两条管道独立。

默认剧本为 **《春物 · 放学后的侍奉部》**：包含完整的当前项目设定包（14 位人物、校园地点与规则、年龄和初始关系、三个原创开场），默认主角为比企谷八幡。另附原创 **《雨后书屋》**，作为创建剧本的完整示例。

本仓库只含 **一个预写的春物演示存档**，展示雪乃、结衣和八幡的多人交流，以及回看、心声、脉络与示意 CG。演示对白没有调用模型。私人剧情、API Key、登录凭据、春物游戏立绘均不在发布内容中。

## 先看演示：无需 API Key

下载仓库或解压发行包，进入包含 `launch.py` 的目录。需要 **Python 3.10+**；游戏运行代码仅使用 Python 标准库，无需 `pip install`、SillyTavern、Ren’Py 或前端构建。

```powershell
python -X utf8 verify.py
python -X utf8 launch.py --check
python -X utf8 launch.py --demo --open
```

默认地址为 **http://127.0.0.1:18772/**。首次启动把 `examples/demo-library/` 复制到本地 `database/roleplay-library/`，已有资料不会被覆盖。

演示直接打开附带存档，可查看人物、回看、脉络、心声、画廊和导出。最后一幕附带示意 CG；阅读到末段后可查看画面并继续。演示模式关闭文本请求与生图，自由输入禁用；它用于了解界面和数据结构，不能进行新的 AI 对话。

停止空闲服务：

```powershell
python -X utf8 launch.py --stop
```

关闭浏览器不会自动停止 Python 服务。切换演示与正式模式前先停止服务。端口占用时使用 `--port 18773`，停止时也传相同端口。

## 正式游玩：配置自己的文本服务

文本客户端目前固定使用 **DeepSeek Flash**。请自行准备能够调用该模型的 DeepSeek API Key，在首次启动创建本地资料库后，隐藏输入配置：

```powershell
python -X utf8 skills/sillytavern-roleplay/scripts/deepseek_client.py --root database/roleplay-library --configure-key
python -X utf8 launch.py --open
```

Windows 配置入口使用当前用户的 DPAPI 保存密钥，文件位于本地资料库 `browser/credentials/`；不应拷贝到其他机器或提交 Git。也支持启动进程中的 `DEEPSEEK_API_KEY` 环境变量；macOS/Linux 使用环境变量方式。**程序不读取 `.env` 文件**，不要把密钥写进示例、README 或代码。

正式启动后从剧本选择页新建故事，或选择演示存档继续。模型请求使用你的账号，费用和额度由服务提供方决定；仓库不提供公共额度。原始玩家输入、相关人物与世界资料、当前分支记忆会发送给文本服务，不能把“本地存档”理解为模型推理离线运行。

只想使用预备图片、暂时关闭新图生成：

```powershell
python -X utf8 launch.py --no-images --open
```

此模式仍可进行正常 DeepSeek 对话。缺少新地点素材时使用现有视觉资源；不会因此启用其他图片服务。

## 自动生图与 Codex 的关系

自动生图需要在本机安装并登录 **Codex CLI**，且该登录环境实际支持内置图像生成。安装和登录方式以 [OpenAI 官方 CLI 文档](https://learn.chatgpt.com/docs/codex/cli) 为准。`codex` 应能在启动进程的 PATH 中找到；只安装 Codex 桌面应用不保证这个命令可用。

网页、人物卡、世界设定、存档、分支和 DeepSeek 对话均由本项目代码处理。生图模块通过常驻 `codex app-server` 调用图片能力；不自动同步当前 Codex 聊天。生图失效时仍可关闭动态图片继续文本游玩，不会静默换成另一家付费服务。

春物的公共美术使用文字身份标签、几何背景和示意 CG；没有附带官方头像或完整表情立绘。原创书屋另有简易 SVG 人物。示意素材用于验证接口与布局，不代表最终画风；正式剧本可导入自己有权使用的头像、表情立绘、背景和参考图。动态插图根据真实剧情生成，不为每轮对话强制配图。

春物设定包是现有项目的人物与世界设定，附带原创开场，**不包含完整小说正文、原作逐字台词或原游戏流程**。初始好感按第一季开篇关系作玩法估计，属于本项目设定，不是官方数值；替换主角时不自动继承八幡的关系。

## 已有功能与当前限制

| 已实现 | 内容 |
| --- | --- |
| 剧本与图鉴 | 世界观、设定集、人物卡、主角卡、多个开场、人物小卡与详细简介 |
| 自由输入 | 【语言】【动作】【环境】【内心】，一条消息可混合，推荐回应同样经过输入流程 |
| 人物与交流 | 人物到离场、可感知片段、独立知识、多人署名、好感与性格态度约束 |
| 画面与声音 | 立绘表情、背景切换、CG 等待与展示、有限额预测图库、共用图库、情绪音乐 |
| 存档与回溯 | 多个存档、树状分支、节点快照、独立记忆；回溯新建分支，保留原档 |
| 回看与导出 | 最近回合在前，各人物署名；回看、脉络、心声及完整故事导出 TXT/Markdown |

这仍是原型：

- 目前**没有存档删除界面**，心声仍是小面板，大页面尚未实现。
- 有最近对白、摘要与记忆筛选，尚未实现按总 token 预算触发的分层长期记忆压缩，也没有接入 Codex 原生上下文压缩。
- 文本端点、模型名和协议目前专门适配 DeepSeek；不能只换其他厂商 Key 就接通。
- 人物知识与现实逻辑有提示和校验，但复杂、长篇剧情仍可能出错，不能保证所有模型回应都完全符合常识。
- 当前验收主要在 Windows 完成；macOS/Linux 运行与 Codex 生图组合仍需实际验证。
- 本项目是本机单用户舞台，绑定回环地址；不是 GitHub Pages 静态网站，也没有远程多用户部署与账号系统。
- 生图服务依赖外部 Codex CLI 协议与能力，响应速度和可用性取决于对应服务。

## 创建自己的剧本

完整字段、对象关系、素材登记和旧档规则见 **[docs/创建剧本.md](docs/创建剧本.md)**。

最少准备故事背景、主要人物和开始处境。剧本包的格式为：

```json
{
  "spec": "yukima_script_v1",
  "world": {},
  "setting_sets": []
}
```

`world` 定义名称、背景、人物资料锚点、设定集 ID 和 `opening_scenes`；`setting_sets` 放人物、地点、物品、规则与事件卡。人物卡可以完整内嵌，也可以引用库内已有 ID。人物展示简介和模型扮演规则应分开；事件是具备前提的可能性，不把未来剧情写成已发生事实。

复制 [examples/rainy-bookshop.json](examples/rainy-bookshop.json)，改成自己的稳定 ID、人设与开场。先运行一次 `launch.py` 初始化本地库，再导入：

```powershell
python -X utf8 skills/sillytavern-roleplay/scripts/worlds.py --root database/roleplay-library import-script examples/rainy-bookshop.json
python -X utf8 skills/sillytavern-roleplay/scripts/worlds.py --root database/roleplay-library list
```

仓库已附带此演示剧本；原样导入只用于理解流程。创建新剧本时更换 ID。导入后刷新选择页，人物不会各自挤成独立剧本入口；已有存档保留原有设定快照。

可以在任何 Codex 聊天引用 [本项目技能](skills/sillytavern-roleplay/SKILL.md)，用自然语言提出：

> 使用这个项目的技能，在项目内资料库创建《海边车站》。背景是现代小镇，主角是成年旅行者，主要人物是两位有各自工作与判断的成年人。故事从雨后的站台开始。请整理人物卡、地点和规则卡、玩家可读简介及两个开场，导入并检查。先不开始游戏。

已有 SillyTavern PNG/JSON 角色卡可这样导入：

```powershell
python -X utf8 skills/sillytavern-roleplay/scripts/tavern.py --root database/roleplay-library import path/to/card.json --alias "角色昵称"
```

主角卡独立导入。春物默认卡见 [examples/hachiman.json](examples/hachiman.json)，原创旅人格式示例见 [examples/protagonist.json](examples/protagonist.json)：

```powershell
python -X utf8 skills/sillytavern-roleplay/scripts/worlds.py --root database/roleplay-library import-player examples/protagonist.json
```

网页不提供上传入口。导入文字不会自动备齐图片。立绘、头像与背景在本地库 `browser/characters.json` 注册；PNG/JPEG/WebP 文件可放 `browser/assets/`，资源 URL 使用 `/media/browser/assets/文件名`。配置示例见演示人物清单 `skills/sillytavern-roleplay/assets/galgame/characters.json`。不同人物不要绑定同一张脸来补缺。

春物已预装，无需再导入；可编辑或学习 [examples/oregairu.json](examples/oregairu.json)。正式模式首次进入选择页默认选中春物，在开场选择页可切换三个开始场景、查看 14 位人物卡及八幡主角卡。演示入口则直接恢复唯一的演示存档。

## 存档、记忆和图库

`examples/demo-library/` 是公开、固定的演示种子，只含一个演示存档。`database/roleplay-library/` 是首次启动建立的私人运行库，已在 `.gitignore` 排除。

每个 session_id 拥有自己的对白、摘要、事实、关系、人物知识与记忆。回溯以真实节点快照新建存档，只继承该点及以前的事件，父档和其他分支继续保留。保存已持久化故事会另建留档；自动回合提交更新当前分支。不会接入 LexThink 全局词库。

预测图库与已发生剧情分开。每棵存档树背景 2、立绘 3、交流画面 1；只有真实采用才释放同类型名额。剧本共用图库复用已采用的背景与交流图，立绘独立，各存档按自身引用解锁；预测图不会提前成为人物记忆。

回看、脉络与心声面板有导出按钮。接口示例：

```text
GET /api/export?session_id=demo000000000001&scope=story&format=txt
```

`scope` 为 `story`、`plot`、`thoughts` 或 `all`；`format` 为 `txt` 或 `md`。导出按发生顺序排列，只读选定存档，不调用模型；完整故事的心声放在独立附录。

## 目录

```text
yukino0.8/
├─ README.md / LICENSE / NOTICE.md
├─ VERSION / manifest.json / verify.py
├─ launch.py
├─ skills/sillytavern-roleplay/
│  ├─ SKILL.md / scripts/ / references/
│  └─ assets/galgame/              网页、示意图片与音乐
├─ examples/
│  ├─ oregairu.json                默认春物完整设定包
│  ├─ rainy-bookshop.json          原创剧本创建示例
│  ├─ hachiman.json / protagonist.json  主角卡示例
│  └─ demo-library/                一个公开演示存档与节点
├─ docs/创建剧本.md
└─ database/roleplay-library/       首次启动创建，Git 忽略
```

这是普通 JSON 文件资料库，不需要安装数据库服务。`verify.py` 检查公共文件哈希和演示库结构，不请求模型；运行库变化不影响发布文件校验。

## 上传 GitHub

推荐仓库名 **`yukino`**，版本标签 **`v0.8`**；不要把整个私人 ai4everything 副本当成这个公共壳提交。

在当前目录初始化 Git，并先查看待提交内容：

```powershell
git init
git add .
git status --short
git commit -m "Prepare Yukino v0.8 public shell"
```

然后创建自己的 GitHub 仓库，按 GitHub 给出的远程地址设置 remote 并 push。也可上传本目录的公共文件，或把 ZIP 放在 Release 中。本交付没有替你创建仓库、提交或上传。

后续自己的存档、上传图片、凭据与任务日志位于被忽略的 `database/`。不要强制添加该目录；要分享一个新演示，应另行整理脱敏、独立的例子放入 `examples/`，并检查相关素材来源。

## 来源与许可

代码基于本地 `sillytavern-roleplay` 适配，保留 [pearyj/sillytavern-cards-skill](https://github.com/pearyj/sillytavern-cards-skill) 上游归属，以 **AGPL-3.0-only** 发布；完整许可证见 [LICENSE](LICENSE)，改动说明见 [NOTICE.md](NOTICE.md)。

原创演示文本和 SVG 示意素材随项目许可分发。五首音乐的录音来自 Kevin MacLeod / incompetech，以 **CC BY 4.0** 单独署名，曲目、来源、作曲归属和哈希见 [音乐署名](skills/sillytavern-roleplay/assets/galgame/music/CREDITS.md)。音乐许可与代码许可不同。

春物角色和作品归原权利方所有；整理的人物设定与来源链接见剧本包，不能把代码许可视为获得原作 IP 授权。公共壳不附带官方角色图库、原游戏立绘或私人角色资料。自行添加的角色卡与图片不因放进本项目而自动获得项目的许可。Yukino 暂定名称不代表与原作品、模型服务商或上游作者的官方关联。
