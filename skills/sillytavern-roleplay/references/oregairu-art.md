# 春物现成立绘来源与导入

此前本地素材库实际使用的来源是 [broscolotos/oregairukan](https://github.com/broscolotos/oregairukan)，人物PNG位于 [usable/chara](https://github.com/broscolotos/oregairukan/tree/main/usable/chara)。仓库说明其内容从Switch版本的《やはりゲームでも俺の青春ラブコメはまちがっている。完》移植；这是**收录原游戏素材的第三方项目，不是官方免费素材授权站**。原游戏图像权利归原权利方，源仓库没有给这些美术提供开放内容许可；本项目不将它们随公共发行包重分发。

## 先找已有图，再少量补画

按此前获取的目录，常用文件夹为：

|文件夹|人物|
|---|---|
|yukino / yui / iroha|雪之下雪乃 / 由比滨结衣 / 一色彩羽|
|komachi / haruno / shizuka|比企谷小町 / 雪之下阳乃 / 平冢静|
|saki / hayama / saika|川崎沙希 / 叶山隼人 / 户冢彩加|
|tobe / zaimokuza / miura / ebina|户部翔 / 材木座义辉 / 三浦优美子 / 海老名姬菜|

该目录与本项目角色ID不完全同名，例如miura对应yumiko，ebina对应hina；登记时使用人物卡的真实ID。此前目录没有独立八幡或相模南文件夹，不能承诺它覆盖当前15位角色或每一种表情；缺失人物、特定服装或状态再使用自己的素材或少量生图，避免批量重复生成已有立绘。第三方仓库的目录可能调整，以实际页面为准。

1. 打开上面的素材目录，选择人物文件夹和PNG。单张打开文件后使用Raw/下载；需要较多素材时可在仓库Code菜单下载ZIP并解压，保留来源记录。比如结衣的 [YUI_SAC01L0.png](https://github.com/broscolotos/oregairukan/blob/main/usable/chara/yui/YUI_SAC01L0.png) 曾用于本地基准立绘。
2. 原始编号不等于情绪标签，需目视确认表情、服装和透明背景。优先选同一套服装、尺寸和画风；不要把视线变化强行当成愤怒/开心，也不要将便服、运动装标为校服。多数此前使用的图是独立透明PNG，不必先拆图；只有下载到图集时才需要拆成单张。头像可从自己选定的立绘裁出。
3. 先运行项目launch.py建立资料库，把挑好的图放到 `database/roleplay-library/browser/assets/oregairu-local/yui/` 之类的目录。可把已确认的表情另存为neutral.png、thinking.png等，保留原文件名与来源、哈希清单。不要替换公共包的SVG文件，也不要拷贝别人的API Key或存档。
4. 推荐在Codex调用**当前项目**的Skill，把素材路径交给它登记。可直接说：

   > 使用这个项目的sillytavern-roleplay技能，把我下载的春物PNG目录导入本项目资料库。根据人物卡ID与真实表情登记avatar、sprites、reference和default_appearance，更新角色图鉴头像与主角引用，保留已有存档和剧本内容。miura是三浦、ebina是海老名，别按文件夹名误绑定。缺的人物和表情先列出来，优先复用现成图，再少量补画；不要重复大规模生图。

5. 自行登记的基本格式是资料库 `browser/characters.json` 下的人物ID条目。以下只展示字段，实际ID与文件必须存在；别覆盖整个文件或删掉其他人物。

```json
{
  "oregairu-core-yui": {
    "name": "由比滨结衣",
    "world_ids": ["oregairu-campus"],
    "avatar": "/media/browser/assets/oregairu-local/yui/neutral.png",
    "reference": "/media/browser/assets/oregairu-local/yui/neutral.png",
    "default_appearance": "school-uniform",
    "sprites": {
      "neutral": "/media/browser/assets/oregairu-local/yui/neutral.png",
      "thinking": "/media/browser/assets/oregairu-local/yui/thinking.png"
    }
  }
}
```

图鉴优先读取设定卡的avatar，因此只写characters.json可能只更新舞台；让Codex同时更新当前目录中的展示头像引用。主角则更新本项目主角卡与visual_manifest_id。**不要改写旧存档冻结的人设或剧情快照来补图**，用素材清单提供视觉覆盖。

导入后刷新/安全重启对应项目服务，检查人物选择小卡、实际舞台表情、画廊和图片URL均可加载，每人使用自己的脸。图片已在本地且注册正确时可以关闭新图生成正常游玩；使用已有素材不需要调用Codex生图。
