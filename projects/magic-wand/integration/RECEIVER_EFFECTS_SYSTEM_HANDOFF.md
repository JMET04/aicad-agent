# Magic Wand Receiver-Effects 系统交接

状态：**接收拓扑与软件接口已冻结 / receiver-effects 裸板候选整改中 / 不构成当前 CAM、PCBA 或量产放行**  
基线日期：2026-08-22

本文件只定义冻结魔法杖与独立 `receiver-effects` 彩屏/音效接收板之间的系统边界。当前产物身份、所有者授权和开放门以 [`CURRENT_SYSTEM_STATUS.json`](CURRENT_SYSTEM_STATUS.json) 为准；系统级总体交接仍见 [`SYSTEM_ENGINEERING_HANDOFF.md`](SYSTEM_ENGINEERING_HANDOFF.md)。这里的“冻结”是配置和接口冻结，不代表物理首件、目标固件、安全、RF/EMI 或生产验证已经通过。

## 1. 本轮冻结配置

### 1.1 Wand 冻结边界

- Wand 的 PCB、外壳、电池/触觉预留、八类手势词典和现有制造候选不因 receiver-effects 子系统而修改。
- 本轮接收侧扩展只能消费已定义的安全协议和手势事件；不得要求 Wand 改板、移动天线、改变电源树、增加显示/扬声器负载或放宽 press-to-arm 约束。
- Wand 仍须在物理按住 ARM 时才允许产生可接受的手势事件；事件本身是遥测/媒体意图，不是负载动作授权。
- Wand 的目标固件构建、烧录、轴向 HIL、真实 AES-CCM/BLE 会话、续航、RF 和首件验证仍为开放门；配置冻结不得被解释为这些门已经关闭。

### 1.2 八通道

- 逻辑通道固定为零基 `0..7`，每个通道绑定一个明确的 peer `device_id`、独立 `session_id`、重放高水位和安全状态。
- “八通道”表示最多八个隔离的逻辑 Wand 会话槽，不表示八路功率输出，也不授权同时驱动外部负载。
- 路由通道、V2 载荷中的 `logical_channel`、外层认证帧的 `device_id/session_id` 和配置槽必须一致；任一不一致都应拒绝并使受影响会话回到安全状态。
- 非零通道只能使用显式协商的 Multichannel V2。Legacy V1 只保留在通道 0 的兼容审查边界中。
- 低压输出策略若未来与媒体接收器共存，仍只能有一个明确 output owner；彩屏和音效不得取得或刷新输出租约。

### 1.3 接收拓扑

- `receiver-effects` 固定为带独立 NINA-B302 的**直接受配对端点**：它自行完成认证握手、profile 协商、会话绑定和重放检查，然后把通过验证的手势事件交给显示/音效调度器。
- 它不是由另一块 receiver 转发事件的中继板；不得新增隐式 UART、广播转发或共享明文会话。凭据烧录、轮换、撤销和调试锁仍须由目标固件与生产流程证明。
- 媒体端点默认只有显示、音效和状态灯权限。即使认证成功，也不得从媒体事件推导危险输出授权。

### 1.4 八类手势 / 八魔咒

以下映射是 receiver-effects 的冻结媒体语义；手势编号仍以 Wand 手势词典为权威：

| 手势 | 魔咒/效果 | 屏幕意图 | 音效意图 |
|---|---|---|---|
| `TAP` | Explosion | 星爆/冲击动画 | 限幅爆炸声 |
| `TWIST_CW` | Fire | 顺时针火焰/旋涡 | 火焰呼啸与轻微爆裂 |
| `TWIST_CCW` | Ice | 逆时针冰晶/旋涡 | 冰晶铃音与裂纹声 |
| `SWISH_LEFT` | Lightning | 左向闪电/彗尾 | 闪电电弧声 |
| `SWISH_RIGHT` | Shield | 右向护盾展开 | 护盾闪光声 |
| `THRUST` | Arcane | 向前奥术脉冲 | 奥术脉冲声 |
| `CIRCLE_CW` | Heal | 顺时针治愈光环 | 治愈铃音 |
| `CIRCLE_CCW` | Portal | 逆时针传送门 | 传送扭曲声 |

配对、已连接、断开、低电量、未知手势和故障使用独立状态效果，不占用八魔咒编号。默认音量、主音量上限和爆炸音限幅只是软件设计约束；实际声压、扬声器温升和失真均为**待证据**。

## 2. GESTURE_EVENT 版本协商

外层安全帧继续使用现有 canonical frame；“V1/V2”在这里指 `GESTURE_EVENT` 载荷 profile，不是通过猜测长度升级外层协议。profile 必须在认证握手中显式协商，并与方向特定流量密钥、peer 和 session 一起生效。

### 2.1 Legacy V1：精确 2 字节

| 字节 | 字段 | 约束 |
|---:|---|---|
| 0 | `gesture_id` | 已定义手势 ID |
| 1 | `confidence_percent` | 当前接受范围 70..100 |

- 载荷长度必须**精确等于 2**，不能接受 0、截断、扩展或尾随字段。
- 只用于单通道兼容审查，不能承载 channel、battery、status、device 或 session 冗余绑定。
- Legacy V1 会话收到 14 字节 V2，或 V2 会话收到 2 字节 Legacy，必须拒绝；禁止自动 sniff、自动降级和同一会话混用。

### 2.2 Multichannel V2：精确 14 字节

V2 字节序由 [`mw_gesture_event_v2.h`](../firmware/include/mw_gesture_event_v2.h) 和配套 codec 定义。多字节整数为大端序：

| 字节 | 字段 | 约束 |
|---:|---|---|
| 0 | `schema` | 固定 `0x02` |
| 1 | `logical_channel` | `0..7` |
| 2 | `gesture_id` | 八类手势之一 |
| 3 | `confidence_percent` | `70..100` |
| 4 | `battery_percent` | `0..100`；未知时固定 `0xFF` |
| 5 | `status_flags` | bit0 ARM；bit1 STAT1；bit2 STAT2；bit3 battery-known；其余位必须为 0 |
| 6..9 | `device_id` | 非零，大端序，必须等于外层认证发送方 |
| 10..13 | `session_id` | 非零，大端序，必须等于外层认证会话 |

V2 的接收事务必须按以下顺序失败关闭：

1. 认证握手明确协商 `MULTICHANNEL_V2`；未支持的 profile 拒绝。
2. 外层帧先完成方向、命令、精确长度、device/session、sequence、freshness 和 AES-CCM 校验。
3. 重放高水位原子持久化成功后，才解码 14 字节载荷。
4. 再次交叉检查载荷内 channel/device/session 与路由槽和外层头一致。
5. 通过后仅投递给媒体效果调度器；手势事件不得直接调用 AUX、隔离开集或低边开关输出。

当前 host 证据已完成：干净构建 `25/25`、CTest `8/8`、cppcheck `9/9` 无发现、证据清单 `37/37` 源文件哈希一致；证据文件 SHA-256 为 `73C595844F2E9526CE5D2C01A84986BA83089CBED20AF60F50E7AE5F5C4D1D70`。这些结果冻结了 host 侧协议、路由、媒体调度和失败关闭语义，但不能替代真实目标 AES-CCM、BLE LE Secure Connections、密钥生命周期、抗回滚持久化、目标构建或八设备并发 HIL；这些门仍为**开放**。

## 3. 独立 receiver-effects PCB 合同

### 3.1 子系统定位

`receiver-effects` 是独立的低风险媒体反馈端点，目标是接收通过认证的手势遥测并驱动彩屏、音效与状态灯。它不替代现有低压 receiver，不拥有安全关键输出，不接触市电、飞行控制、推进或急停功能。

“低风险”只表示媒体副作用与负载动作隔离，不表示无电气风险。USB 输入、背光、I2S 功放、扬声器、RF、热和声压仍须设计与验证。任何故障的默认状态是：背光关闭或静态故障画面、功放硬件静音、RGB 故障指示；不得产生外部负载动作。

### 3.2 冻结硬件接口与精确附件

当前独立 KiCad 工程目标板框为 `50.3 mm × 42.3 mm`、4 层；它不修改 Wand PCB，也不复用旧 receiver 作为中继。板上核心器件固定为 NINA-B302、TPS62162 3.3 V 降压、USBLC6 USB ESD 保护和 MAX98357 I2S 类 D 功放；USB-C 输入按合格外部 `5 V / 2 A` 电源设计，不依赖 PD/QC 协商。当前 PCB 正在修正功率线宽、局部 GND 回流和 CPL 原点，故下表是已冻结的电气/附件合同，不是当前 CAM 放行声明。

| 功能 | 精确器件/接口 | NINA-B302 模块焊盘 → GPIO | 失败安全要求 |
|---|---|---|---|
| 240×240 彩屏 | Waveshare `1.28inch LCD Module`，GC9A01，SKU `19192`，外接 J2 8 针 | SCK 52→P0.19；MOSI 50→P0.20；CS 51→P0.17；DC 48→P0.21；RST 49→P0.22；BL 47→P0.23 | J2 物理顺序固定为 `VCC/GND/DIN/CLK/CS/DC/RST/BL`；复位期间 CS 非活动、背光关闭 |
| 数字音效 | 板上 MAX98357A；外接 XHXDZ `30MM-4Ω3W-TFHM`、LCSC `C50387216`，J3 JST-PH 引出 | BCLK 1→P0.13；LRCLK 2→P0.14；DIN 3→P0.15；SD/MODE 4→P0.16 | SD/MODE 硬件默认静音；扬声器为 BTL 差分输出，`SPK+`、`SPK-` 任一端都禁止接系统 GND |
| 状态灯 | 3.3 V RGB LED + 独立限流 | R 5→P0.24；G 7→P0.25；B 8→P1.00 | 上电默认熄灭或确定故障色，不得悬空 |
| 电源 | J1 USB-C 5 V 输入；USBLC6、1.5 A PTC、TPS62162 3.3 V/1 A；MAX98357 使用 5 V | 电源域，不占应用 GPIO | 使用合格 `5 V / 2 A` 外部供电；过流/ESD/反灌、欠压静音和峰值/热验证仍须台架证明；不得由 Wand 电池供电 |
| 调试/生产 | SWD、复位及关键电源/总线测试点 | 按 PCB pin contract | 量产后调试锁、凭据烧录与返修流程待定义 |

显示模组和扬声器都是外接附件，不进入 PCBA 贴装清单；J2 连接显示线束，J3 连接 JST-PH 扬声器尾线。附件选型、连接器方向和 BTL 禁接地要求必须同时出现在 BOM、装配说明、Bring-up 清单和壳体设计中。

### 3.3 电源、EMI 与机械边界

- 将功放/扬声器脉冲电流、背光电流、数字 3.3 V 和 RF 供电预算分开；在原理图阶段给出 worst-case、电源启动顺序、bulk/高频去耦和欠压静音分析。
- 类 D 扬声器回路、SPI/I2S 时钟和背光 PWM 远离 NINA PIFA 及其净空；保持连续回流面，不在高速信号下切割地平面。
- 扬声器差分线成对、短且远离天线/USB；是否需要 EMI 滤波只能由精确功放参考设计和预扫结果决定。
- 屏幕 FPC/连接器、功放、扬声器、USB 与天线的相对位置必须进入 3D 堆叠；显示窗公差、扬声器声腔/出音孔、维修路径、螺钉和塑料材料均为机械接口。
- 媒体渲染、SPI DMA 或音频填充不得饿死 BLE、安全协议、watchdog 或输出安全任务；优先级、执行预算和故障注入须由目标 HIL 证明。
- 当前整改的主干线宽目标为：`USB_VBUS_RAW/USB_VBUS_5V` 0.8 mm、`SPK_PLUS/SPK_MINUS` 0.6 mm、`3V3/BUCK_SW` 0.5 mm；细间距器件只允许有界、短距离的 0.25 mm 焊盘颈缩，并须报告每网窄段数量、长度和占比。
- 原生 DRC 不会证明功率承载或回流连续性。放行前还须确认 5 V/3V3 平面入口过孔、NINA/功放局部 GND 回流、天线禁布、铜到板边和峰值压降/温升。

## 4. 跨子系统接口与变更影响

| 接口 | 提供方 → 使用方 | 冻结内容 | 变更后必须重做 |
|---|---|---|---|
| Wand gesture | Wand classifier → secure queue | 8 个 ID、confidence、ARM gate | 手势向量、代表性用户数据、轴向 HIL |
| Secure frame | pairing/session → receiver runtime | direction、device/session、sequence、freshness、精确长度、AES-CCM | 协议负向向量、packet capture、持久化掉电测试 |
| Payload profile | authenticated handshake → codec/router | Legacy=精确2；V2=精确14；禁止自动降级 | 两种 profile 的交叉长度/降级/重放测试 |
| Channel binding | router → 8 个 session slot | channel 0..7、peer 唯一、会话隔离 | 八设备并发、跨槽注入、单槽故障隔离 |
| Media intent | router → effect scheduler | 手势只触发媒体，不触发输出 | 每个魔咒视觉/音频 golden vector 与 no-actuation HIL |
| Display | renderer → GC9A01A adapter | 240×240 RGB565 场景；SPI/复位/背光由目标适配器负责 | 目标构建、帧时序、DMA/故障、实屏 HIL、EMI |
| Audio | synth → I2S/功放 adapter | 16 kHz 合成意图、静音和软件限幅 | I2S 时序、硬件静音、声压/温升/削波、EMI |
| Power | USB supply → receiver-effects | 5 V/2 A 计划输入、独立媒体负载 | 启动/浪涌/欠压/热/USB 兼容和整机 RF |

独立媒体板获得事件的拓扑已经冻结为**直接受配对端点**；不允许由另一个 receiver 隐式转发。任何改回中继、共享凭据或额外广播链路的提议都属于系统架构变更，必须重开协议、安全、BLE 连接数、时延、威胁模型和 HIL 门禁。

## 5. 验证分层

| 层级 | 所需证据 | 当前结论 |
|---|---|---|
| L0 接口静态检查 | 精确 V2 字节序、字段范围、pin budget、变更影响 | V1 exact-2、V2 exact-14、8 槽和直接端点合同已冻结 |
| L1 Host 单元/负向向量 | V1/V2 codec、profile 混用拒绝、8 通道隔离、8 魔咒差异、音频限幅、no-actuation | **已通过：25/25 build、8/8 CTest、cppcheck 9/9、证据哈希 37/37** |
| L2 目标构建 | 固定 NCS/Zephyr、receiver-effects devicetree、ELF/HEX/map/config 哈希 | **待证据** |
| L3 EDA | 独立原理图/PCB、精确 MPN/封装、ERC/DRC、天线/回流/功率线宽/CPL 原点审查 | `50.3 × 42.3 mm`、4 层候选已存在；功率线宽、局部 GND 回流和 CPL 原点整改/复核中，**未放行** |
| L4 板级 Bring-up | 电流限制上电、5 V/3.3 V、复位、SPI、I2S、背光、硬件静音、SWD | **待证据** |
| L5 物理媒体 | 实屏帧率/撕裂、八效果可辨识、声压/失真/温升、故障静音 | **待证据** |
| L6 系统 HIL/安全 | 八设备、跨通道攻击、BLE/AES-CCM、掉电持久化、断链/低电/故障、媒体绝不驱动输出 | **待证据** |
| L7 EMI/RF/热/机械 | 天线性能、SPI/I2S/类D预扫、USB/功放热、屏幕/扬声器/壳体装配 | **待证据** |
| L8 DFM/首件 | BOM/LCSC、CPL、Gerber/drill、装配图、工艺、AOI/ICT、首件检验 | 旧 CAM 包因功率线宽审计失败而 **REJECTED**；整改后可重新评估裸板，PCBA **NOT READY** |

当前任何既有 receiver-effects Gerber/Drill/CAM 都不是订购输入。只有整改后的权威 PCB 再次通过 ERC、原生 DRC、未连接、原理图一致性、功率线宽/颈缩、回流路径、板框和 CPL 原点审计，并重新生成且哈希绑定 CAM 后，才可把**裸板候选**提交报价。当前 BOM 仍有 7 个空 LCSC 编码，故 PCBA 明确为 **NOT READY**，不得用裸板通过代替 PCBA 物料放行。

## 6. DFM 与生产交接最低要求

1. 维护 NINA-B302、Waveshare SKU 19192、MAX98357A、TPS62162、USBLC6、USB-C、C50387216 扬声器、J2/J3 连接器的精确 MPN、生命周期与受控 datasheet；附件不得误列为 PCBA 贴装件。
2. 用真实厂商 land pattern 重建并独立核对 pin-1、模块焊盘、FPC 方向、扬声器极性、USB 屏蔽和测试点；禁止用通用相似封装代替。
3. 建立完整 BOM/LCSC/AVL、CPL 原点/旋转、DNP、替代料规则、装配面、回流限制和手焊禁区；补齐当前 7 个空 LCSC 前不得标记 PCBA Ready。
4. 输出同一提交哈希下的原理图、PCB、Gerber、PTH/NPTH、BOM、CPL、装配图、坐标与制造清单；每个文件都需 SHA-256 绑定。
5. 预留并标注 VBUS、3V3、GND、RESET、SWD、SPI、I2S、AUDIO_SD、TFT_BL 和关键电流测量点；定义 ICT/功能测试序列。
6. 完成面板化、板边/FPC/USB 机械限制、天线区域禁布、铜到板边、阻焊桥、热焊盘、散热铜、泪滴/过孔和可制造性复核。
7. 首件只允许受控原型。裸板门可在 EDA/DFM/CAM 哈希门关闭后单独放行；PCBA 仍须关闭物料、目标固件、台架、EMI/RF、热、声学和机械门，禁止把两种成熟度混为一谈。

## 7. 系统工程经验

- **冻结接口，不混淆成熟度。** Wand 配置可以冻结，同时目标固件、首件和生产门继续开放。
- **控制面与媒体面分离。** 输出租约/安全状态属于控制面；屏幕、音效和 RGB 只消费遥测，不能反向取得动作权限。
- **版本必须显式协商。** 精确 2 字节和精确 14 字节是两个 profile；长度猜测和自动降级会制造歧义与降级攻击面。
- **关键身份做冗余绑定。** route channel、payload channel、device、session 与认证帧相互核对，让跨通道或跨会话注入在进入效果层前失败。
- **把“未运行”写进证据。** 静态合同、host 向量、目标构建、EDA、HIL、EMI 和首件是不同层；上一层通过不能替代下一层。
- **低风险副作用也要预算。** 彩屏和音效不会直接驱动负载，但会引入 2 A 电源、类 D EMI、RF 去敏、热、声压和实时调度风险。
- **独立 PCB 降低变更半径。** 媒体电源、连接器、壳体和器件替换不应重开 Wand PCB；但协议、凭据、RF 共存和用户体验仍是系统级变更。
- **每个接口都要有 change impact。** 字节、引脚、器件、功率、连接拓扑或壳体变化都必须列出受影响的代码、EDA、机械、制造和验证门。
- **先做失败状态，再做效果。** 上电静音、背光关闭、无动作、断链安全和媒体任务失效隔离必须先被证明，再优化动画和音色。
- **从“画得出来”升级为“系统可交付”。** Drawing generator 的输出只回答图形是否存在；multidisciplinary system designer 还要绑定需求、协议、固件、EDA、电源、RF/EMI、机械装配、BOM、制造文件、测试证据和开放风险。
- **原生 ERC/DRC 是必要条件，不是充分条件。** 本轮 DRC 清零后仍发现所有高电流网络被路由成 0.25 mm，说明必须增加按网络的线宽/颈缩长度审计、载流/压降检查、平面入口过孔和回流路径审计。
- **几何原点也是跨域接口。** CPL 原点/旋转、Gerber 坐标、板框、连接器方向和机械基准必须来自同一权威 PCB；任一项漂移都可能让“电气正确”的板无法装配。
- **失败的 CAM 要显式作废。** 一旦上游 PCB 或审计结论改变，旧 Gerber/Drill/BOM/CPL 必须标记 `REJECTED` 并隔离，不能依赖文件时间或操作者记忆防止误下单。
- **门禁应由机器证据和人工跨域复核共同关闭。** 推荐固定链路：接口合同 → host 向量 → 目标构建 → ERC/DRC/一致性 → width/return-path/origin 审计 → CAM 哈希 → 实板 Bring-up/HIL；后级结果不能倒推前级已满足，也不能跳级授权 PCBA。

## 8. 未完成门禁

- 直接受配对端点的目标凭据烧录、轮换、撤销、调试锁和真实 BLE/AES-CCM：**待证据**。
- receiver-effects 权威 PCB 的功率线宽/有界颈缩、局部 GND 回流、平面入口过孔、天线区和板边复核：**整改/待复核**。
- `50.3 × 42.3 mm`、4 层权威板在整改后的 ERC/DRC/未连接/原理图一致性全量重跑：**待最终证据**。
- CPL 原点/旋转审计、CAM 重生成和逐文件 SHA-256 绑定：**待证据；旧 CAM 已 REJECTED**。
- BOM 中 7 个空 LCSC、AVL/替代料/DNP 和装配工艺：**未关闭；PCBA NOT READY**。
- V1/V2 认证协商的目标握手 transcript、禁降级策略和目标端互操作：**待证据**。
- NINA-B302 receiver-effects 目标构建、烧录、SWD 日志和二进制哈希：**待证据**。
- 八台 Wand/八槽并发、跨槽注入、掉线、重连、重放和持久化掉电 HIL：**待证据**。
- 实际屏幕、背光、I2S 功放、扬声器、RGB 的台架与故障注入：**待证据**。
- USB 电源、浪涌/欠压、功放峰值、温升、声压、EMI/RF 和整机共存：**待证据**。
- 显示窗、FPC、扬声器声腔、出音孔、维修和首件装配：**待证据**。
- 独立安全/电气/机械/EMC/制造评审、PCBA 与生产授权：**未授权**。

## 9. 下一接手顺序

1. 从当前权威 `50.3 × 42.3 mm`、4 层 PCB 修正功率主干与有界颈缩，复核局部 GND 回流、平面入口过孔、天线区和板边，不改 Wand。
2. 重跑 ERC、原生 DRC、未连接和原理图一致性，并输出逐网 width/neckdown、return-path 与 CPL origin 审计；任何一项不通过都保持旧 CAM `REJECTED`。
3. 从通过门禁的同一 PCB 重生成 Gerber/Drill/BOM/CPL，校验板框/层数/钻孔/坐标并做 SHA-256 绑定；此时才可把裸板候选送嘉立创报价。
4. 补齐 7 个空 LCSC、AVL/DNP/替代料与装配规则后另行评估 PCBA；不得把外接屏幕和扬声器误作贴装件。
5. 把显式 V1/V2 profile 协商落入目标握手，用固定 NCS/Zephyr 完成目标构建、烧录与真实 BLE/AES-CCM 互操作。
6. 完成八通道、多设备、屏幕/音效、功率、EMI/RF、热、声学、机械装配和故障 HIL，再决定 PCBA/生产授权。

## 10. 建议技能

- `kicad`：独立 receiver-effects 原理图、PCB、ERC/DRC 和制造输出。
- `jlcpcb`：只在 EDA/物料/DFM 门关闭后生成裸板或 PCBA 交接包。
- `aicad-agent:aicad-model-3d`：屏幕、扬声器、USB、天线和壳体的真实堆叠与碰撞审查。
- `emc`：类 D、SPI/I2S、USB、背光 PWM 与 NINA 天线共存审查。
- `bom`：精确 MPN、AVL/LCSC、生命周期和替代料冻结。
