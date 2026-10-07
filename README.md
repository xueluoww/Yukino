# Yukino 0.5 · 剧本与壳

一个可以导入世界观、人物与开场，自由推进故事的浏览器 AI 视觉小说原型。

**Yukino** 是暂定项目名，**0.5** 是本次公共壳版本；底层舞台版本为 **5.6**。项目运行在本机 Python 服务和浏览器中。文本由 DeepSeek Flash 生成，动态图片由已登录的 Codex CLI 原生生图服务生成，两条管道独立。

## 玩春物前：图片来源与补图方法

**人物设定已附带，完整人物美术没有附带。** 仓库中的春物人物小卡/立绘位置使用带姓名的原创 SVG 占位标签，基础背景与演示 CG 也有 SVG 示意图；这些不是官方头像或正式立绘。原创《雨后书屋》人物同样是简易 SVG。

0.5另附两张**由 Codex 原生生图制作的空场景图**：春雨侍奉部和春日薄暮走廊，供终卷原创短篇使用。文件在 `skills/sillytavern-roleplay/assets/galgame/storyline-backgrounds/`，`prompts.json`记录生成要求，`library.json`记录校验值；它们参考开发阶段的场景素材制作，不是原作截图。仓库没有把开发者个人图库、完整人物表情库、官方游戏立绘或网上搜到的图片打包进来。

**补齐人物图最方便的方式是在 Codex 里调用本项目技能：**

1. 下载项目后先运行一次 `python -X utf8 launch.py --demo --open`，建立项目内资料库；已有资料不会覆盖。
2. 在 Codex 打开该项目，引用 `skills/sillytavern-roleplay/SKILL.md`，要求为**这个项目内的春物剧本**准备素材。可以直接使用以下请求：

   > 为本项目春物剧本补齐人物头像和透明背景立绘。雪乃、结衣、八幡等主要人物准备多种表情，相模南等配角准备基础表情；保持统一画风、制服和人物外貌。先准备每人一张基准图，再以该图为参考扩展表情。按实际人物卡ID注册素材，更新本项目的 browser/characters.json 和人物头像引用，校验每个人绑定自己的图片。只修改本项目，保留原存档；完成后列出素材清单。

3. 需要**支持原生生图且已登录的 Codex CLI 环境**；生成会使用相应服务的额度，并需要等待。也可提供自己有权使用的参考图/现成立绘，让 Codex导入并登记。参考图以每人自己的基准图为准，避免把角色画成另一人的脸。
4. 配置自己的 DeepSeek Key 后，停止演示服务，再用 `python -X utf8 launch.py --open`正式游玩。开启动态生图后，缺少的场景和适合剧情的CG可以继续生成；**仅勾选开关不会自动批量补全所有人物表情**，首次人物库仍需按上面准备。演示模式不调用生图。

自行导入时，建议把 PNG/JPEG/WebP 文件放在项目资料库 `database/roleplay-library/browser/assets/`；透明立绘用 PNG/WebP。浏览器地址使用 `/media/browser/assets/文件名.png`，在该库 `browser/characters.json` 中按人物卡ID登记 `avatar`、`sprites`（如 `neutral`、`thinking`、`soft`）和相应参考图，主角头像在主角卡中登记。具体结构见 [素材配置](skills/sillytavern-roleplay/references/browser.md)。只复制图片文件不会自动建立人物绑定。

准备好实际图片后，可从游戏设置“调整当前画面”或画廊“调整这幅画面”补充提示词、重画并比较采用；**SVG占位图不能使用这项重画功能**。生成与导入的图片保存在你本机，API Key不随图片包发布。人物与作品的权利归原权利方，代码许可不等同于人物素材许可；音乐来源和署名见 [音乐说明](skills/sillytavern-roleplay/assets/galgame/music/CREDITS.md)。

默认剧本为 **《春物 · 放学后的侍奉部》**：包含完整的当前项目设定包（15 位人物、校园地点与规则、年龄和初始关系、三个原创开场），默认主角为比企谷八幡。另附原创 **《雨后书屋》**，作为创建剧本的完整示例。

本仓库只含 **一个预写的春物演示存档**，展示雪乃、结衣和八幡的多人交流，以及回看、心声、脉络与示意 CG。演示对白没有调用模型。私人剧情、API Key、登录凭据、春物游戏立绘均不在发布内容中。

## 本次更新：预制线、画面版本与记忆实验

发行版本为0.5（引擎5.6），此前的0.8公共包是历史命名。新增“调整画面”：补充提示词，以原图为参考生成新版、比较后采用。原图与旧档保留；已经走过的情节只加入画廊。SVG示意素材不支持重画，正式生成需要可用的Codex原生服务。

预制故事线支持固定主线、自由目标阶段和汇合收束；修复提前推进、达标后重复台词、条件死路和背景漏入画廊。新游戏可选择《春物·终卷短篇：下一次开门》，这是含剧透的原创互动改编，不是原著全文。自由对白需要自己的文本服务，未读完当前回应不能发送下一轮。

分层记忆已独立实验，但本轮**不启用**：原系统24/24，原型23/24；输入量约减半，却泄漏了角色不该知道的信息。运行版本保留原记忆系统。详细结果与原型见 [实验报告](experiments/memory-v56/记忆实验报告.md)，本轮验证见 [验证报告](docs/0.5验证报告.md)。

## 剧本与壳

**剧本是你编写和导入的世界；壳是负责运行它的主程序。** 剧本由世界观、设定集、可选世界玩法和素材构成。壳提供加载与校验、浏览器舞台、通用状态接口、模型管道和独立分支存档。

剧本可以携带自己的玩法规则代码：春物可以使用委托簿，其他剧本可以定义战斗、调查或经营。符合当前模块接口的规则随剧本导入，不需要先在主程序中为每种玩法写专门实现。超出接口能力的新机制仍需要扩展主程序。

这次还更新了存档管理与横向分支页面、长期记忆整理、故事时间、物品与事件、关系和剧情阶段，并修复普通消息与玩法请求混用的问题。完整说明见 [更新日志](CHANGELOG.md)、[剧本与壳](docs/剧本与壳.md) 和 [创建剧本](docs/创建剧本.md)。

仓库现提供完整源码，也可下载 [更新后的公共包](https://github.com/xueluoww/Yukino/raw/refs/heads/main/yukino0.5-public.zip)。解压 ZIP 后进入其中的 yukino0.5-public；使用源码时直接进入仓库根目录。两种方式均只附一个预写演示存档。

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

春物公共人物美术是文字身份标签，基础场景与演示CG为SVG示意；另附两张AI生成的终卷空场景图。没有附带官方头像或完整表情立绘，补图方法见本文前部。原创书屋另有简易 SVG 人物。示意素材用于验证接口与布局，不代表最终画风；正式剧本可导入自己有权使用的头像、表情立绘、背景和参考图。动态插图根据真实剧情生成，不为每轮对话强制配图。

春物设定包是现有项目的人物与世界设定，附带原创开场，**不包含完整小说正文、原作逐字台词或原游戏流程**。初始好感按第一季开篇关系作玩法估计，属于本项目设定，不是官方数值；替换主角时不自动继承八幡的关系。

## 已有功能与当前限制

| 已实现 | 内容 |
| --- | --- |
| 剧本与图鉴 | 世界观、设定集、人物卡、主角卡、多个开场、人物小卡与详细简介 |
| 自由输入 | 【语言】【动作】【环境】【内心】，一条消息可混合，推荐回应同样经过输入流程 |
| 人物与交流 | 人物到离场、可感知片段、独立知识、多人署名、好感与性格态度约束 |
| 画面与声音 | 立绘表情、背景切换、CG 等待与展示、有限额预测图库、共用图库、情绪音乐 |
| 存档与回溯 | 独立横向分支页、节点读档与回溯、管理、备注、回收站、存档包导入导出；分支记忆隔离 |
| 回看与导出 | 最近回合在前，各人物署名；心声大页面；故事导出 TXT/Markdown |
| 剧本自带玩法 | 目录包、受限 Python 规则、模块依赖和版本固定；通用记录卡与动作按钮 |
| 时间与世界状态 | 日期、时刻、行动耗时、跨日、物品归属、事件与承诺、信任与熟悉程度 |
| 长期记忆 | 后台纪要、历史检索、上下文预算控制；原文保留与精确前缀继承 |
| 剧本工具 | 创建模板、检查引用与模块运行、校验后导入；旧 JSON 包仍兼容 |

这仍是原型：

- 时间与事件已经记录，但通用到期触发、地点开放关闭等自动后果尚未完成；剧情阶段仍主要由模型结合真实进展判断。
- 长期记忆已实现后台摘要、历史检索和 UTF-8 字节预算控制；尚未实现多层语义摘要与精确 token 计量，没有接入 Codex 原生上下文压缩。
- 文本端点、模型名和协议目前专门适配 DeepSeek；不能只换其他厂商 Key 就接通。
- 人物知识与现实逻辑有提示和校验，但复杂、长篇剧情仍可能出错，不能保证所有模型回应都完全符合常识。
- 当前验收主要在 Windows 完成；macOS/Linux 运行与 Codex 生图组合仍需实际验证。
- 本项目是本机单用户舞台，绑定回环地址；不是 GitHub Pages 静态网站，也没有远程多用户部署与账号系统。
- 生图服务依赖外部 Codex CLI 协议与能力，响应速度和可用性取决于对应服务。

## 创建自己的剧本

创建目录包与玩法模块先看 [剧本与壳](docs/剧本与壳.md)，完整字段、对象关系、素材登记和旧档规则见 **[docs/创建剧本.md](docs/创建剧本.md)**。

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

新剧本可以用 `create_script.py` 生成完整示例骨架，再用 `validate-script` 检查、`import-script` 导入；可选 `world_gameplay` 携带玩法代码。完整协议见 [世界玩法接口](skills/sillytavern-roleplay/references/gameplay.md)。

主角卡独立导入。春物默认卡见 [examples/hachiman.json](examples/hachiman.json)，原创旅人格式示例见 [examples/protagonist.json](examples/protagonist.json)：

```powershell
python -X utf8 skills/sillytavern-roleplay/scripts/worlds.py --root database/roleplay-library import-protagonist examples/protagonist.json
```

网页不提供上传入口。导入文字不会自动备齐图片。立绘、头像与背景在本地库 `browser/characters.json` 注册；PNG/JPEG/WebP 文件可放 `browser/assets/`，资源 URL 使用 `/media/browser/assets/文件名`。配置示例见演示人物清单 `skills/sillytavern-roleplay/assets/galgame/characters.json`。不同人物不要绑定同一张脸来补缺。

春物已预装，无需再导入；可编辑或学习 [examples/oregairu.json](examples/oregairu.json)。正式模式首次进入选择页默认选中春物，在开场选择页可切换三个开始场景、查看 15 位人物卡及八幡主角卡。演示入口则直接恢复唯一的演示存档。

## 存档、记忆和图库

`examples/demo-library/` 是公开、固定的演示种子，只含一个演示存档。`database/roleplay-library/` 是首次启动建立的私人运行库，已在 `.gitignore` 排除。

每个 session_id 拥有自己的对白、摘要、事实、关系、人物知识、时间、物品、事件、玩法状态与记忆。回溯以真实节点快照新建存档，只继承该点及以前的事件，父档和其他分支继续保留。保存已持久化故事会另建留档；自动回合提交更新当前分支。不会接入 LexThink 全局词库。

预测图库与已发生剧情分开。每棵存档树背景 2、立绘 3、交流画面 1；只有真实采用才释放同类型名额。剧本共用图库复用已采用的背景与交流图，立绘独立，各存档按自身引用解锁；预测图不会提前成为人物记忆。

主界面和游戏内均有存档管理入口。每条故事外层只列起始父档，点击打开独立横向分支页；支持拖动、底部滑条、退出和节点读档。节点管理提供改名、备注、导出与回收；删除可恢复，游戏内当前档受保护。

回看、脉络与心声页面有导出按钮。接口示例：

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

剧本新版本不会自动改写旧档的设定与玩法快照。希望启用新版玩法时，在新分支中升级；先备份自己的 `database/`，旧档的历史代码不可删除。

这是普通 JSON 文件资料库，不需要安装数据库服务。`verify.py` 检查公共文件哈希和演示库结构，不请求模型；运行库变化不影响发布文件校验。



## 来源与许可

代码基于本地 `sillytavern-roleplay` 适配，保留 [pearyj/sillytavern-cards-skill](https://github.com/pearyj/sillytavern-cards-skill) 上游归属，以 **AGPL-3.0-only** 发布；完整许可证见 [LICENSE](LICENSE)，改动说明见 [NOTICE.md](NOTICE.md)。

原创演示文本和 SVG 示意素材随项目许可分发。五首音乐的录音来自 Kevin MacLeod / incompetech，以 **CC BY 4.0** 单独署名，曲目、来源、作曲归属和哈希见 [音乐署名](skills/sillytavern-roleplay/assets/galgame/music/CREDITS.md)。音乐许可与代码许可不同。

春物角色和作品归原权利方所有；整理的人物设定与来源链接见剧本包，不能把代码许可视为获得原作 IP 授权。公共壳不附带官方角色图库、原游戏立绘或私人角色资料。自行添加的角色卡与图片不因放进本项目而自动获得项目的许可。Yukino 暂定名称不代表与原作品、模型服务商或上游作者的官方关联。
