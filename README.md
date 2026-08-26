# 蕾米埃尔 Codex 桌宠

![蕾米埃尔](assets/readme/ramiel.jpg)

一只会实时反映 Codex 工作状态的 Windows 桌面宠物，基于“桌宠公开版”全模型改造。
多项目并行时自动聚合状态：只要有任务在思考就保持 `think`，任一任务完成弹出
`happy` 并显示微信风格气泡，点击气泡或宠物即可收回；Codex 征求权限时弹出粉色
审批窗口，可直接“允许 / 总是允许 / 拒绝”。

## 下载

[![Download](https://img.shields.io/badge/Download-remiel--codex--pet%20v1.0.0-FF7FA3?style=for-the-badge&logo=github)](https://github.com/doorinsea/remiel-codex-pet/releases/latest/download/remiel-codex-pet-v1.0.0.zip)

⬇️ **免安装版（解压即用）**：[下载 v1.0.0](https://github.com/doorinsea/remiel-codex-pet/releases/latest/download/remiel-codex-pet-v1.0.0.zip)
—— Windows，无需安装 Python，解压后双击 `蕾米埃尔codex桌宠.exe` 即可。也可到
[Releases](https://github.com/doorinsea/remiel-codex-pet/releases) 页面选择版本，
或点右上角 **Code → Download ZIP** 获取源码。

## 状态图鉴

![状态图鉴](assets/readme/gallery.jpg)

## 状态语义与素材设计思路

| 桌宠状态 | Codex 触发时机 | 素材文件 | 设计思路 |
| --- | --- | --- | --- |
| silent | 默认待机 | silent.gif | 安静循环，不打扰 |
| think | 任意会话 `task_started` / `user_message` | think.gif | 思考锁定：只允许完成时切到 happy，单击、键盘连击等都不会打断 |
| happy | 任一任务 `final_answer` / `task_complete` | happy.gif | 完成庆祝，保持 5 秒；单击可提前收回；若仍有任务在思考则回 think，否则回 silent |
| work | 键盘 2 秒内连击 8 次 | work.gif | 手动唤醒动画，与 Codex 状态无关，播完自动退出 |
| afterclick | 单击宠物（非思考/完成状态） | afterclick.gif | 单击反馈，播放一次回 silent，不打开任何窗口 |

## 素材使用途径

- `素材/*.gif`：桌宠 5 个状态动画，由 `silent_pet.py` 运行时加载并循环播放，随宠物窗口缩放重渲染。
- `素材/菜单图标/*.png`：右键菜单应用图标（微信 / Steam / WPS / 自定义应用）。
- `assets/readme/`：README 宣传图与状态图鉴（`ramiel.jpg` 为本项目宣传图）。

菜单中的应用**全部运行时自动探测安装位置**（注册表卸载项 → 常见路径 → 显式路径），
探测不到的项自动隐藏；任何电脑 clone 下来都开箱即用，无个人硬编码路径。

## 快速开始

### 运行

1. Windows + Python 3.10+，依赖 `pillow`、`pynput`。
2. 直接运行：`python silent_pet.py`；或跑 `build_pet.bat` 打包出 `蕾米埃尔codex桌宠.exe`
   （脚本自动使用 PATH 里的 `py -3` / `python`，也可用环境变量 `PYEXE` 指定）。
3. 单实例：重复启动会自动退出。

### 配置 config.json（可选）

把 `config.example.json` 复制为 `config.json`（放在 exe / 脚本同目录，或用环境变量
`CODEX_PET_CONFIG` 指定位置），即可自定义右键菜单应用。`launch_apps` 存在时会**完全替代**
默认列表；每项字段：

| 字段 | 说明 |
| --- | --- |
| name | 菜单显示名 |
| match | 注册表卸载项 DisplayName 匹配关键字（可多个） |
| exe | 可执行文件名，用于拼接安装目录 |
| paths | 常见安装路径（支持 `*` 通配符） |
| path | 显式路径（存在则优先使用） |
| icon | 菜单图标 PNG 文件名（可省略，省略时用首字兜底图标） |

`config.json` 已被 .gitignore 排除，不会进仓库。

## 交互

- 左键单击：收回气泡（happy 时）/ 播放单击动画（其余状态）
- 左键双击：收起气泡与菜单，并打开 Codex（自动探测桌面应用，未运行则启动）
- 按住拖拽：移动宠物，气泡与审批窗跟随
- 右键单击：快捷菜单（自动探测已安装应用）
- 右下角缩放把手：按住拖动实时调整大小（120~400px）
- 右键双击：退出桌宠
- 键盘 2 秒内连击 8 次：work 动画
- 思考中（think）状态锁定：单击、键盘连击等不会切换到其它状态，直到思考完成转 happy

## 气泡

Codex 完成思考后，宠物上方弹出**微信风格白色圆角气泡**（粉色不透明），文案为
“爱思考先生/小姐，你的任务已经完成了~”。默认保持 5 秒自动收起（期间单击可提前收回）；
多条会话并行时，只要还有任务在思考，气泡收起后宠物会回到 think。气泡跟随宠物拖拽移动。

## 审批窗口

Codex 征求权限时，宠物弹出**粉色不透明审批窗口**，只显示授权原因，可直接点击：

- 允许 → 点回 Codex 应用里的 Allow
- 总是允许 → 点回 Always allow
- 拒绝 → 点回 Deny

通过 Windows UI 自动化把决定点回 Codex 应用的审批卡片（按钮中英文都匹配，未渲染时自动重试；
右键点审批窗可临时关掉，不做任何决定）。命令被批准/拒绝后窗口自动关闭。

“Approve for me（自动审批）”模式下：升级命令出现后先观察 3 秒，并用 UI 自动化探测应用里
是否真的出现审批卡片，**有卡片才弹窗**；自动批准但执行较慢的命令不会误弹。桌宠启动时
不重放历史未决审批。

## Codex 状态检测原理

后台线程轮询 `~/.codex/sessions` 下的 `rollout-*.jsonl` 会话日志（支持多线并行）。
只跟踪**真实用户任务**，忽略 Codex 内部自动审批评估线程（guardian）：

- 任意会话 `task_started` / `user_message` → think（思考中）
- 任意会话 `agent_message(phase=final_answer)` / `task_complete` → happy + 气泡（5 秒）
- `function_call` 带 `sandbox_permissions=require_escalated` → 观察 3 秒 + 探测审批卡片，
  确认需人工授权才弹窗；直到对应 `function_call_output` 出现才视为已处理
- 思考中判定：会话处于 busy 且日志文件 **5 分钟内有新写入**；中断/漏写完成标记的
  陈旧会话自动失效，避免“全部完成仍卡 think”

## 项目结构

```
蕾米埃尔codex桌宠/
├── silent_pet.py          # 主程序
├── uia_approval.ps1       # 审批窗口 UI 自动化脚本
├── build_pet.bat          # 一键打包 exe
├── config.example.json    # 菜单配置模板
├── README.md
├── 素材/                  # 状态动画 GIF 与菜单图标
└── assets/readme/         # README 宣传图与状态图鉴
```

## 已知限制

- 只能感知写入本机 `~/.codex` 的会话（Codex 桌面版与 Windows 命令行版）；WSL 里跑的
  Codex 会话看不到。可用环境变量 `CODEX_PET_SESSIONS` 指向其它会话目录。
- “完成”判定依赖会话日志中的 `final_answer` / `task_complete`；异常中断的会话靠
  5 分钟无新写入自动失效。
- 代码仅支持 Windows（依赖 Tk 透明窗口、Win32 API 与 UI 自动化）。

## 素材来源与版权

- 状态动画与菜单图标基于“桌宠公开版”素材整理；仅限个人学习与非商业展示使用，
  再分发请保留原作者署名并遵守原仓库授权范围。
- `assets/readme/ramiel.jpg` 为本项目宣传图，版权归项目作者所有。
- 本项目为个人非官方项目，与 OpenAI / Codex 官方无关，不存在隶属、合作或赞助关系。

## 与公开版的区别

- 去掉“单击打开对话窗 + API 配置”整套功能；
- `happy` 由“播一次”改为“保持 5 秒，单击可提前收回”；
- `think` / `happy` 由 Codex 会话状态驱动，支持多会话并行聚合；
- 新增微信风格气泡与“单击收回”交互；
- 新增审批窗口：Codex 征求权限时弹出，可直接允许 / 总是允许 / 拒绝；
- 忽略 Codex 内部自动审批评估线程（guardian），避免误报“任务完成”；
- 应用与 Codex 安装位置全部运行时自动探测，无个人硬编码路径，可直接公开分享。
