# 校历、白天安排与考勤（世界模式）

壳提供 `school_calendar.py`，剧本只声明数据。只有新建世界模式档的冻结配置包含 `school_calendar` 时启用；沙盒、无配置旧档不产生考勤。课表不是玩家行动，玩家可离开或不参加；默认只记录事实与供老师回应的来源，不自动处分、扣分或接受谈话。

在 `world.school_calendar` 或 `world_defaults.school_calendar` 中声明：

```json
{
  "version": 1,
  "start_weekday": 0,
  "school_weekdays": [0,1,2,3,4],
  "holidays": [{"day":23,"name":"合成假日"}],
  "vacations": [{"start":106,"end":147,"name":"暑假"}],
  "special_days": [{"day":40,"name":"考查日","classes":false}],
  "periods": [{"id":"first","start":530,"end":580,"title":"第一节课"}],
  "teachers": {"teacher":{"location":"classroom","periods":["first"]}},
  "notice_locations": ["classroom","corridor"],
  "consequence": "reminder"
}
```

地点和教师 ID 必须存在；单日最多8个不重叠课程，每段最长180分钟，与日程执行合同一致。`start_weekday` 为开局星期，0=周一；已有确定故事日期时采用该日期的星期。节假日、休假均为开局相对天数，不借参考校历改故事年份。`special_days` 优先，可声明补课或活动替代正课。原著未明确的授课分工、课时、假期起止必须标为模拟安排。

新档编译时，主角教室来自主角卡或对应 `protagonist_defaults.classroom_id`；无绑定主角不被当作该校学生。NPC课程来自实际班级绑定，教师来自明确的授课安排；调用原有路线、目标与活动占用，不瞬移。课堂占用不代表学会知识、完成考试或获得成绩。普通上课默认按到达窗口；返家默认按出发窗口，见 [日程](npc-schedules.md)。

考勤使用当前日滚动卡 `attendance:player`，每节保存窗口、预期地点、实际地点、观察时刻与状态；历史留在分支事件包，不无限复制全年度卡进每轮视图。`present/late/absent/left_early/unknown` 分别表示检查时在场、晚到后在场、检查时未在场、曾在场后离开、无检查依据。中途开档或长等待跳过的课程保留未知，不追认整天缺勤。出勤采用边界及回合采样，不能声称每一分钟都经过连续监测。

老师只有实际在预期教室点名、或在上课时实际看见学生，才获得本人私有的带来源知识。走廊同地点 ID 不等于目击，需要既有接触/观察范围。点名未见表示该次未见；走廊目击只表示看见人在走廊，不推断整日缺勤。其他人物看不到这张知识卡。默认 `reminder` 不改变关系；可选 `talk` 发出可拒绝的谈话机会，`trust` 从实际观察扣一次信任（每教师每日至多一次），无来源不执行。普通请假解析及考查成绩系统尚未新增。

游戏内打开“地图 → 今日课表”，查看上课日、假日及当前档的出勤。页面只读，不在查看时造卡；未知与未参加严格区分。现有长等待仍受模拟预算约束，中间未模拟时段不补写人物活动。

春物模板：原著事件6项保留，新增42项原创校园机会，总计48项。每周约两项的午休、阅读、练习、校园咨询穿插考查准备、健康检查、球技活动、学期结束与始业安排；假期免正课，不关停所有自由活动。依据为 [千叶县立高中日课表](https://www.chiba-c.ed.jp/toke-hs/topnav/gakushuu/nittukahyou.html)、[高中年度行事参考](https://cms2.chiba-c.ed.jp/abikohigh/wysiwyg/file/download/14/11195)、[内阁府祝日历史表](https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv)。祝日使用2013-04-08起的参考表映射，仅用于校历排期，不确认原著年份，不解锁该年的世界知识；未提前引入2016年才施行的山之日。春物现有开局仍为高二春季、年月日未确认。
