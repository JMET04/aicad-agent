# 魔法杖手势目标集成说明 Rev A0

## 当前结论

便携式 C11 手势核心已经完成 8 类动作、拒识、实体按键门控和 250 ms 防连击测试；当前机器没有 nRF Connect SDK、Zephyr `west` 或 ARM 交叉编译器，因此本目录现在仍不能宣称已经生成可刷入 NINA-B302 的镜像。

## 受控输入契约

`mw_gesture_classify_relative_window()` 和 `mw_gesture_stream_push()` 只接收已经完成偏置校准和轴向变换的“魔法杖坐标系”样本：

- `+X`：由握把指向杖尖；
- `+Y`：按键朝上握持时指向使用者左侧；
- `+Z`：指向实体按键一侧；
- 陀螺仪单位为 dps，加速度单位为 g，`delta_time_ms` 必须使用真实采样间隔。

PCB 到魔法杖坐标的几何关系为：`wand +X = PCB +Y`、`wand +Y = PCB -X`、`wand +Z = PCB +Z`。LSM6DSV16X 裸传感器轴还必须先按数据手册的封装轴向变换到 PCB 坐标，不能把寄存器原始 XYZ 直接传给识别器。首板必须用六面静置和逐轴正向旋转测试冻结最终 3×3 符号/置换矩阵。

## 建议传感器配置

- LSM6DSV16X：加速度计 ±4 g，陀螺仪 ±2000 dps，ODR 240 Hz；
- 初次启动 I²C 使用 100 kHz，通过示波器边沿和错误率测试后才升到 400 kHz；
- 使用 `IMU_INT1` 数据就绪或 FIFO 水位中断，不用非确定性轮询延时模拟采样周期；
- 启动后静止采样至少 2 s，求陀螺仪零偏和重力模长；运动或震动时不得更新零偏；
- 每个样本填入真实时间差。识别器接受 2–25 ms，丢样或超限时应终止当前窗口并重新开始。

## 运行循环

```c
mw_gesture_stream_t stream;
mw_gesture_result_t result;

mw_gesture_stream_init(&stream);

/* 每次 IMU 数据就绪： */
sample = read_calibrate_and_remap_lsm6dsv16x();
if (mw_gesture_stream_push(
        &stream,
        &sample,
        physical_arm_button_is_held(),
        monotonic_time_ms(),
        &result)) {
    queue_distinct_haptic_pattern(result.id);
    queue_authenticated_gesture_event(result.id, result.confidence_percent);
}
```

实体按键松开时，流式窗口立即清空。无线侧只发送已经通过认证、计数器防重放和新鲜度检查的事件；接收器的输出动作仍必须经过 `mw_state_machine_receiver_command()` 的租约和最大脉冲宽度限制。

## 默认动作策略

8 类手势都应先产生不同的本地触觉反馈和遥测事件。首板阶段不要直接把圆圈、前刺或轻敲映射到外部执行器。只有在代表性用户数据集通过后，才逐项批准低压、非安全关键动作映射；任何映射都不得绕过实体按键、接收器租约、链路超时和输出脉冲上限。

## 首板验收顺序

1. 断开电池，仅用限流 USB 电源确认 3V3、I²C 和中断脚；
2. 六面静置确认加速度轴向、符号、重力模长和温漂；
3. 单轴旋转确认陀螺仪轴向与符号；
4. 采集每类动作至少 30 次及静止/走路/放桌等负样本；
5. 分用户训练/验证，不能把同一用户的相邻窗口随机拆进训练和测试；
6. 在触觉马达开启、低电量、USB 充电和无线发射四种干扰状态下复测；
7. 记录混淆矩阵、每类精确率/召回率、拒识率、每小时误触发、端到端延迟；
8. 通过后再冻结阈值、目标固件哈希和可回滚升级包。

## 目标镜像尚需完成

- 固定 nRF Connect SDK/Zephyr 版本和 NINA-B302 板级定义；
- 集成 ST 官方 LSM6DSV16X 寄存器驱动、INT1、I²C 和计时器；
- 集成 BLE LE Secure Connections SC-only、设备唯一凭据和 AES-CCM 回调；
- 增加安全启动、签名升级、反回滚、掉电计数器持久化、看门狗和欠压处理；
- 用真实首板完成 HIL、无线范围、电源瞬态、充电温升和电池保护测试。
