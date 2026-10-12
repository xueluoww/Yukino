# Codex原生生图修复与验证

2026-10-12，公开版本保持Yukino 0.9，内部版本保持5.7.10-world-trial。

## 修复内容

旧子进程使用自定义visual_service提供方且没有指定独立CODEX_HOME。它与桌面Codex共享认证存储；错误路由、凭据刷新和并行客户端组合存在影响原登录的风险。此前仅验证登录及握手，未证明实际出图。没有保留本次用户失败的HTTP原始记录，因此不能断言每次退出登录都由同一个错误触发。

本次将请求改回Codex内置openai提供方，显式启用image_generation。子进程的CODEX_HOME固定在本资料库browser/image-service/codex-home，图片也保存在其中的generated_images。游戏按实际输出目录验证并复制到自己的素材库，不再只认全局.codex/generated_images。

只读复用桌面Codex登录时，仅读取当前access token，通过app-server的实验性chatgptAuthTokens模式在内存提供身份；不复制、不提交、不刷新共享refresh token，不改写桌面auth.json。401时只允许同一账号由Codex本体已经更新的访问凭据；没有新访问凭据就停止并显示登录提示，不触发桌面登出。桌面账号改变后需重新检测。

“为Yukino单独登录”启动官方CLI浏览器登录，明确使用独立目录和file凭据存储。该独立登录由Codex管理自身续期，桌面凭据不参与。文件型桌面登录可只读复用；仅在系统钥匙串中保存的凭据不通过此方式提取，请使用单独登录。旧CLI不支持实验性模式时应显示协议错误，不偷偷切到API密钥或别的供应商。

启动页增加“试画一张（使用额度）”。检测、工具安装和保存配置不试画；只有明确点击试画才提交一张合成测试图片。generation_verified仅在真实图片返回、路径与格式验证成功后置真。模型只回文本、返回越界路径、缺失参考图或图片额度不足，均不能视为成功，错误提示保留在画面任务里。

## 实际验证

- 真实文生图一次：蓝色三角形、白底；PNG落盘973690字节，约58.39秒。
- 真实参考图编辑一次：传入上图，将蓝色改成红色；通过Player.native_image保存至browser/assets并返回/media/browser/assets/URL，PNG1445036字节，约54.44秒。新旧图片均检查，编辑后为红色三角形。
- 两次都是新建隔离资料库和合成输入，没有发送玩家存档或剧本私有文本。使用本机现有Codex账号，会消耗相应图片额度。
- 两次前后桌面Codex auth.json哈希完全相同。登录检测、生成和关闭不执行account/logout，不改写全局配置。没有在测试中调用共享刷新接口。
- 75项针对图片、登录和启动器的隔离回归通过；包含18项新增认证、原生路由、参考图转发、Base64落盘、假成功拒绝、越界输出拒绝、额度提示、外部刷新拒绝、账号切换以及独立登录环境检查。
- 不将这些结果解释为全项目所有玩法回归通过；此前两个地点旧断言的失败记录仍保留。没有进行人物一致性或透明立绘质量评测，可灵自动绘图仍未接入。

## 使用

正常停止旧游戏并关闭旧启动页，再打开新启动页。点击“检测登录与连接”；如有需要，选择“为Yukino单独登录”，完成官方浏览器授权后再检测。可以明确点击“试画一张”检查本账号图片能力，再选择“使用Codex生图”并正常启动游戏。配置供下次启动使用，不会强杀已有服务或改变当前存档。

当前选择“仅已有图片”时继续保持该选择，不因更新自动开启收费生成。新导入的私人剧本及游玩数据不进入GitHub或发行ZIP。

## 源码

scripts/codex_image_auth.py处理访问凭据与目录隔离；scripts/image_service.py处理原生提供方、协议事件、真实图片及错误；scripts/runtime_v4.py验证当前服务输出目录并保留明确失败提示。首启页改动在launcher/image_setup.py、setup.py、image-setup.js、welcome.html；回归在tests/test_codex_images.py。

认证规则参考[官方认证文档](https://developers.openai.com/codex/auth)与[app-server账户模式](https://developers.openai.com/codex/app-server)。不要把面向公共Responses API的ChatGPT-plan路由当作Codex原生图片路由；[该公共路由的预览限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)明确区分支持能力。
