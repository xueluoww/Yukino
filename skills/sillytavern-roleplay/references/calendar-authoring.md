# 固定事件、课程与校历制作方法

用于世界模式；预制视觉小说分镜另见 [预制线制作](storyline-authoring.md)。壳提供运行代码，剧本声明数据。先登记角色、地点、必要物品与可达路线，示例中的 `teacher/student/classroom/corridor` 必须替换为本剧本 ID。学生角色填写 `classroom_id`，主角通过卡或 `protagonist_defaults.classroom_id` 绑定教室，无绑定主角不自动算作学生。

## 固定活动

将对象加入完整包的 `world.world_defaults.fixed_events`（独立世界文件用 `world_defaults.fixed_events`）：

```json
{
  "id":"library-open-day",
  "title":"阅读交流日",
  "description":"开放阅读交流，可以询问、旁观或离开。",
  "day":8, "minute":960, "duration":50,
  "location":"classroom",
  "participants":["teacher","student"], "excluded":[],
  "notice_locations":["classroom"],
  "schedule_override":true, "public_schedule":true, "participation_policy":"choice",
  "sources":[], "date_basis":"原创模拟排期，不是原著既定日期。"
}
```

`day` 从开局第1天起算；`minute` 是当天分钟（16:00=960）。最多64项，ID不重复，单项1–180分钟，不跨午夜。人物列表最多30个 NPC，不得含 `player`。`participation_policy:"choice"` 要求公开排期，`participants` 仅是优先考虑人选，不是已报名名单；到准备出发的时刻，模型依据本人性格、目标、安排、身体状态和有向关系决定参加、拒绝或稍后考虑。愿意才形成私有目标，路线、时间、占用仍由壳审核；当前人在场也不能代替意向判断。可选活动不覆盖课程、承诺或返家。

省略策略时保留旧的 `scheduled` 日程兼容行为，不表示已有实际出席；仅该策略下 `schedule_override` 可覆盖普通日程，保留承诺和关键例外。`excluded` 是作者明确的不可参加例外，不应拿来表达普通“不想参加”，普通意愿交给本人判断。春物48项活动均采用 `choice`，课程仍由校历单独处理。

玩家可以邀请原本不想参加、或未列为候选的人物。邀请先成为真实听闻，人物结合自身状况与好感、熟悉、信任回应；拒绝不会暗中变成参加目标。本人答应后由目标判断或带实际来源的承诺检测建立活动目标，需绑定公开活动 ID 和真实地点；还未到场不能写成参加。到场记录仅证明本人愿意且实际在场，不自动证明报名、完成比赛、吃过午餐、交了费用或取得名次。玩家现场出现也仅证明在场/旁观。

新增自动参加判断每人每活动每天最多2次请求（允许短暂延期后重新考虑），不限制玩家邀请、对白或自由行动；网络失败/额度耗尽保留“未决定”，不代人物答应。每人作者日程最多8项、模型提议最多4项；合成课程、活动与实际承诺的当日运行卡最多16项，超量机会不能挤掉原有承诺及普通安排。作者应避免过密冲突，校验与隔离试玩必须检查真实目标、移动和到场，不以 HTTP 成功代替证明。

`public_schedule: true` 将标题和时段提前公布到“事件 → 预期事件”；省略或 false 不公开。这些是学生和老师都知道的公共公告，模型视图与事实账本从冻结剧本投影同一份公告，不需要玩家先打开页面，也不为每个学生复制几十张公告卡。预期表不显示私有目标、未来台词和结果；查看不转授他人的私有知识。实际开始、实际到场另行记录，现场观察才产生带来源的发生与在场知识。已结束活动退出预期表，公告仍只证明当初的排期，历史事件保留。

描述只写机会与环境，不能预先写“玩家拿到书”“大家吃了便当”“某人已经认识主角”；物品、关系与结果来自实际结算。最多10个 HTTPS 来源链接，原著相关事件与原创日常分别标注，参考校历不改变故事年代。

## 课程与休息日

同一 `world_defaults` 添加：

```json
{
  "school_calendar": {
    "version":1, "start_weekday":0, "school_weekdays":[0,1,2,3,4],
    "periods":[
      {"id":"first","start":530,"end":580,"title":"第一节课"},
      {"id":"second","start":590,"end":640,"title":"第二节课"}
    ],
    "holidays":[{"day":22,"name":"示例假日"}],
    "vacations":[{"start":106,"end":147,"name":"暑假"}],
    "special_days":[{"day":40,"name":"校内活动日","classes":false}],
    "teachers":{"teacher":{"location":"classroom","periods":["first"]}},
    "notice_locations":["classroom","corridor"],
    "consequence":"reminder",
    "basis":"原创模拟课时，假日以剧本背景为准。", "sources":[]
  }
}
```

星期0=周一、6=周日。有确定故事日期时按实际星期；相对时间用 `start_weekday`。周末、祝日、假期暂停普通课，`special_days` 优先，可设补课或活动替课。假期首尾天均包括。最多8节不重叠课程，每节不超过180分钟，不能凭课堂占用授予知识或成绩。教师明确绑定地点和课时，不推断所有老师给所有班授课。

课表是预期，玩家仍自行行动。老师只能通过实际点名/目击获得私有知识；没有记录保持未知，首次中途观察不能证明迟到。默认 `reminder` 不扣分；可选 `talk` 提供可拒绝的谈话机会，`trust` 在实际缺席观察后每教师每日扣一次信任。没有自动处分、带回教室或替玩家接受邀请。详情见 [校历接口](school-calendar.md)。

“事件 → 预期事件”展示未来七天课程、已公布的活动及假期；“地图 → 今日课表”展示当天与采样出勤。活动替课日还需固定事件来表达活动机会；目前没有通用请假、自动评分与完整教学系统。

## 验证和导入

1. 完整结构参考 `assets/world-templates/oregairu-script.json`，保留自己的世界与角色。
2. 使用 `scripts/worlds.py --root "隔离资料库" validate-script "包文件"` 验证，再在隔离库 `import-script "包文件"`；测试勿指向正式资料库。
3. 新建世界模式档，确认冻结的 `browser_world_definition.config` 含活动、校历；验证未知 ID、重叠课时及非法字段会拒绝。
4. 试玩活动前、开始、到场、结束边界，以及周末、假期、补课、考勤来源、未参加自由、预期表分页；检查 NPC 真实位置，不以发送成功代替到场证明。
5. 验证后按授权导入目标库并建新档，旧档冻结旧剧本，不自动获得新增活动。

实现：`scripts/fixed_events.py`、`school_calendar.py`、`npc_schedule.py`、`schedule_runtime.py`、`world_heartbeat.py`；展示：`assets/galgame/engine-ui.js`、`world-map.js`。剧本无需携带这些运行代码。
