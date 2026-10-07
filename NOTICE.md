# 来源与适配

本技能由 Codex 于 2026-10-04 为用户制作，是 pearyj/sillytavern-cards-skill 的 Codex 适配作品。

上游：https://github.com/pearyj/sillytavern-cards-skill

上游采用 GNU Affero General Public License version 3，本适配以 AGPL-3.0-only 分发，完整文本见 LICENSE。保留上游归属；这是本地衍生版本，不是上游作者维护的官方 Codex 版本。

已改写：角色与独立剧情存储、Codex 对话控制、世界书筛选、Python 角色卡解析、原子存档、并发版本与重试防重复；不依赖或修改 OpenClaw SOUL.md/MEMORY.md。未复用上游 JavaScript 实现。

assets/demo-card.json 中的「林灯」是本适配附带的原创成年角色，用于试玩及验证。

## Bundled music

The recordings in assets/galgame/music/*.mp3 are by Kevin MacLeod (incompetech.com), under Creative Commons Attribution 4.0, rather than the code license. See assets/galgame/music/CREDITS.md and library.json for track names, composition credits, source URLs, and checksums. These recordings are packaged unchanged; runtime playback may loop and crossfade. https://creativecommons.org/licenses/by/4.0/

## Yukino 0.5 公共壳

本版本由本地舞台派生，当前更新到 5.6，新增剧本自带玩法接口、分支存档管理、基础长期记忆及世界状态，保留项目启动入口、离线演示、原创示例数据与上游 AGPL-3.0-only 归属。公开壳未包含私人资料库、原作品角色图像或原游戏立绘。演示对白为预写文本，SVG 为原创示意素材；音乐保留独立 CC BY 4.0 署名，见 skills/sillytavern-roleplay/assets/galgame/music/CREDITS.md。

默认附带《春物 · 放学后的侍奉部》的世界观与人物设定包，包含 15 位人物和三个原创开场。人物与作品归原权利方所有，人物卡保留资料来源链接；代码许可不授予原作角色或作品的知识产权。新增开场与演示对白由本项目编写，不打包小说正文、官方台词或原游戏剧情。公共春物 SVG 为文字身份标签、几何背景与示意 CG，不是官方人物画像。


## 0.5 图片来源

春物人物仅提供原创SVG姓名标签，不附带完整人物立绘。终卷短篇附带两张Codex原生生图生成的无人背景，生成描述和哈希在assets/galgame/storyline-backgrounds的prompts.json、library.json（项目根下须加skills/sillytavern-roleplay前缀）。玩家补齐的人物和动态图片不包含在公共发行包。安装与補图方法见项目README开头。
