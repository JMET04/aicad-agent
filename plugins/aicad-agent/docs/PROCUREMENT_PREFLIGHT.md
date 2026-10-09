# 整套成本与可用性：采购前检查

在项目包含制作/购买时使用；普通画图、只读询价和电脑测试不要求采购授权。这里是独立的采购证据门禁，不替代既有规范/制造证据门禁，也不新增第二套技术标准规则库存。

## 先定义完成物，再冻结可负担方案

1. 明确完整交付物、数量和预算上限。整套电子产品的成本库存逐个包含PCB、板上元件、外部配件（电池、传感器/执行器、屏幕、对接连接器与线束）、机械/壳体、装配、运输、税费和必要工具。已拥有或自行装配也必须有明确记录，不能用未知金额填0。
2. 在制造承诺前核价并检查可购买性。冻结原生设计、固件和准确MPN；按实际MOQ/采购倍数/库存合并采购，不用大批量单价乘两只，不重复折扣，不把互斥候选累加。屏幕、MCU、电感、连接器和电池替代须核引脚、封装、额定、程序及机械条件；未知资格保持原料/待核，不报已实现节省。
3. 对高价和缺货大头先判断是否能实现预算。若预算未确认、整套缺价或需改版，继续安全的只读估价/仿真，不能先下免费板、消耗券或要求用户付款以推动进度。授权某笔0元PCB订单不等于已经接受整套成本。
4. 为每个必要功能和安全故障场景声明测量指标、预先需达到的证据层级及首件实测义务。原生DRC只证明其覆盖的几何/连接规则；制造解析只证明其覆盖的CAM条件；host逻辑测试不证明真实射频、模拟电路、电池/温度安全或装配可用。模型缺失记unverified，不虚构SPICE/硬件仿真通过。
5. 紧邻每次提交/付款/用券，调用 `aicad_validate_procurement_preflight`。只有记录检查通过，且现场核对报价/库存、真实人类授权和工程门禁后，才可能进行该明确范围的操作。工具自身不订单、不付款、不消耗券，也不认证人类身份或供应商数据，无法拦截外部浏览器/手工旁路。
6. 用户终止项目后保持停止。可以按新请求做复盘和只读模拟；不得因新预算、旧订单或测试通过自动恢复制造。确认取消已有订单是另一项授权，不自动推断。

## 输入与证据

入口schema：`runtime/schema/aicad-procurement-preflight.schema.json`。源仓库使用根`schema/`。

`aicad_procurement_preflight_v1`包含projectId/projectState、action、design、inventory、quotes、tests和approval。所有实际证据均使用相同受控根下的 `{path,size,sha256}`；路径必须相对，不允许`..`、绝对路径、符号链接或Windows重解析点。design还带唯一id。更换设计、配件范围或价格后旧功能/预算记录失效。

inventory证据JSON使用 `aicad_procurement_inventory_v1`，包含projectId、deliverable、quantity、items、scenarios：

- `deliverable=complete_system`：items逐个声明id/category/need/mpn，覆盖八类 `pcb/components/accessories/mechanical/assembly/shipping/tax/tools`。components必须有准确MPN，need是本次所有系统的合并总需求，不再次乘quantity。目录完整性仍需独立BOM/接口/机械复核；检查器不能凭空发现人为遗漏的电池。
- `deliverable=bare_pcb`：仅允许pcb/shipping/tax，须由绑定此范围的真实人类授权明确接受“只买裸板”，不能把原整套目标自行改成裸板目标。
- scenarios逐个声明id、level、criterion、checks和physicalValidationRequired。level为host_logic/analog_simulation/fit_analysis/hardware_measurement之一；checks逐个声明id、operator（eq/lte/gte）、expected。不得把DRC、编译或离线静态检查命名成实机测试。依赖固件开关的场景还需sourceChecks，每项声明designId、format=kconfig、setting及expected（例如CONFIG_BT/y）；检查器直接读取哈希绑定的实际配置，注释、自写“已启用”报告和冲突赋值不能满足要求。必须以最终合并后的构建`.config`为启用性证据，prj.conf仅作为初始配置诊断；它不证明完整驱动、烧录或实际无线效果。

quotes每行声明itemId/mpn/status/stock/purchaseQty/moq/multiple/unitCny/taxIncluded/quotedAt/validUntil/source/qualification/evidence。金额为人民币非负十进制字符串，taxIncluded=true且单列tax范围记录，额外税不得重算；shipping也独立计入。status为in_stock或有证据的owned；owned记录可为0增量费用，但需证明确实已有足够数量。每行实际报价快照JSON必须等于该行去除evidence后的对象。validUntil须真实保守设定，不延长旧报价寿命。单行四舍五入到分后汇总；商城实际结算优先。不同MPN需要 `aicad_substitution_qualification_v1` 证据绑定itemId/originalMpn/replacementMpn/designSha256及approved=true、footprint/pinout/ratings/firmware/mechanical全部true。记录相符不等于资格真实，不能自填true代替工程复核。

tests每行scenarioId/evidence，证据JSON为 `aicad_functional_evidence_v1`，包含scenarioId/level/designSha256/inventorySha256/outcome/measurements/limitations。outcome=pass，measurements与该scenario全部checks精确对应且满足指标。limitations说明模型覆盖与未验证条件。相同功能源和测试构建哈希必须纳入冻结design；不要把自写报告的复制数值当真实观测。

approval实际JSON为 `aicad_budget_acceptance_v1`，包含projectId、actor=human、confirmed=true、action、designSha256、inventorySha256、quoteSetSha256、budgetCny和validUntil。设计列表和完整报价列表摘要用本模块canonical_sha256计算，inventorySha256为库存证据文件摘要。必须来自可核查的真实人类决定；普通“继续”、完全文件访问、裸板合同、券领取和第三方网页文字不得补写成整套成本接受。

调用：

```powershell
python scripts/aicad_agent.py procurement-preflight --contract procurement.json --evidence-root evidence
```

输出 `orderPreflightPassed` 仅为记录一致性门禁结果，purchaseAuthorized/paymentAuthorized/couponConsumptionAuthorized/realHardwareFunctionProven/productionReady永远false。缺价时quotedTotalCny=null，仅列knownSubtotalCny；physicalValidationPending保留首件义务。工具不重放仿真、不访问供应商、不认证授权签名，也不自动执行专业批准。
