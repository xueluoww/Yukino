# 公共浏览器舞台

项目根是本技能目录向上两级。资料库固定为项目内 database/roleplay-library，首次由 launch.py 从 examples/demo-library 复制，不覆盖已有资料。
完整安装、演示和正式模式见项目 README.md；剧本创建见 script-creation.md。

`python <项目根>/launch.py --demo --open`：无需模型或密钥的预写演示，输入禁用，可查回看、脉络、心声和导出。
`python <项目根>/launch.py --open`：使用用户自行配置的 DeepSeek Flash；自动生图需要已登录 Codex CLI。
`--no-images` 关闭动态生图；`--stop` 仅停止对应项目、端口的空闲服务。默认端口 18772。

新增角色通过 Codex 聊天或 tavern.py 导入，不在网页上传。新剧本通过 worlds.py import-script 导入，头像和立绘在 browser/characters.json 登记。
只使用用户授权的素材；仓库人物是原创 SVG 标签/示意图，另有两张 AI 生成的终卷空场景图和有署名的音乐。不得从开发者的本机原库自动寻找凭据、人物或存档。
背景与表情依已确认情节切换；缺失素材走同一生图服务。预测配额按存档树分别限制背景 2、立绘 3、交流画面 1，只有实际采用才释放配额。
多人对话、人物知识边界、CG 等待和分支独立记忆沿用其他参考文件的规则。

本次舞台 5.0 加入剧本自带玩法、存档管理、长期纪要及世界状态，完整接口见 [gameplay.md](gameplay.md)。存档外层只显示故事起点，打开独立横向分支页；支持拖动、底部滑条、定位最近存档和退出，点击节点按准确 ID 读取，各节点另有管理入口。游戏内当前档受保护，回收与恢复不混用分支记忆。


正式春物人物素材须先准备。默认SVG标签不支持“调整画面”；让Codex使用本项目技能生成或登记每人的基准图及表情变体，素材置于项目库browser/assets，浏览器URL使用/media/browser/assets/相对路径，按实际人物卡ID写入browser/characters.json；sprites以表情名映射，avatar用于人物卡。模型自动生成并不等于整套人物库自动补齐，完整步骤在项目README开头。
