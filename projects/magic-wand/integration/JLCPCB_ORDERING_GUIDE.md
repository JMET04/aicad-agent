# 嘉立创下单指南（魔法杖 + 接收器 A1）

日期：2026-08-23

两块板都是**裸板（bare PCB）下单**：只传 Gerber + 钻孔，不选 PCBA。BOM/CPL 随包提供，仅供后续贴片审查用，本次订单不要勾选贴片。

## 准备

登录嘉立创下单系统（EDA 下单或官网下单均可）。免费打样通常每单限 5 片、尺寸有限制，两块板尺寸都满足常规免费规则；如果提示付费，按你之前说的直接付款即可。

## 第一单：魔法杖主板

上传文件：[JLCPCB_WAND_REV_A0_GERBER_DRILL.zip](D:/CAD绘制插件/github-release/aicad-agent/projects/magic-wand/electronics/manufacturing/jlcpcb-wand-rev-a0/JLCPCB_WAND_REV_A0_GERBER_DRILL.zip)

按 `jlcpcb-order-parameters.json` 设置：

| 参数 | 值 |
|---|---|
| 板子 | 魔法杖控制器 Rev A0 |
| 数量 | 5 片 |
| 尺寸 | 15 × 80 mm |
| 层数 | 4 层 |
| 板厚 | 1.6 mm |
| 外层铜厚 | 1 oz |
| 阻焊 | 黑色（免费不满足时用默认绿油） |
| 表面处理 | ENIG 沉金（优先，按实时报价决定） |
| 过孔盖油 | 塞孔/盖油 |
| 阻抗 | 不要求 |
| 板内编号 | 去掉 |
| 拼板 | 单板 |
| 沉金/金手指/半孔/包边 | 否 |

该板已冻结：原生 ERC 0、DRC 0/0/0，23/23 封装权威测试通过。

## 第二单：接收器彩屏/音效板 A1

上传文件：[JLCPCB_RECEIVER_EFFECTS_REV_A1_GERBER_DRILL.zip](D:/CAD绘制插件/github-release/aicad-agent/projects/magic-wand/electronics/manufacturing/jlcpcb-receiver-effects-rev-a1/JLCPCB_RECEIVER_EFFECTS_REV_A1_GERBER_DRILL.zip)

按 `jlcpcb-order-parameters.json` 设置：

| 参数 | 值 |
|---|---|
| 板子 | 魔法杖接收器 Rev A1 |
| 数量 | 5 片 |
| 尺寸 | 60 × 50 mm |
| 层数 | 4 层 |
| 板厚 | 1.6 mm |
| 外层铜厚 | 1 oz |
| 阻焊 | 黑色（免费不满足时用默认绿油） |
| 表面处理 | ENIG 沉金（优先） |
| 过孔盖油 | 塞孔/盖油 |
| 阻抗 | 不要求 |
| 板内编号 | 去掉 |
| 拼板 | 单板 |

该板状态：原生 ERC 0、DRC 0/0/0；NINA-B302 模块下方接地参考面覆盖率 96%（插件量产门禁要求 98%）。对裸板打样原型**可用**，仅量产前需按整改项补足。

注意：接收器板上有两处 NINA 模块焊盘内过孔（RESET_N pad 19、GND pad 6），属于原型妥协；上传后在嘉立创 CAM 预览里确认这两处钻孔位于焊盘内、无异常报错即可。

## 下单后

1. 两单的 CAM 预览与本地 ZIP 哈希一致（魔杖包 SHA-256 `EC3C07314F5ED346…`，接收器包 SHA-256 `F87E17C82B541FE3…`）。
2. 等板回来后先做限流上电，不要直接接真实电池/喇叭；按 `SYSTEM_ENGINEERING_HANDOFF.md` 第 4 节的“首次上电”顺序执行。
3. 之后需要烧录 NINA-B302 目标固件（需要 nRF Connect SDK/Zephyr 工具链），再做真实 BLE/屏幕/音效/HIL 验证。
