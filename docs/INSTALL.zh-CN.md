# aicad-agent 安装和使用指南

## 推荐方式：从 GitHub marketplace 安装

需要 Codex CLI 或 Codex 桌面版、Git，以及 Python 3.10 或更高版本。

安装固定版本：

```powershell
codex plugin marketplace add JMET04/aicad-agent --ref v1.10.0
codex plugin add aicad-agent@aicad-agent
```

安装后执行：

```powershell
codex plugin list
```

确认 `aicad-agent` 为 `installed, enabled`，然后新建一个 Codex 任务。插件技能和 MCP 工具在新任务中加载最可靠。

更新：

```powershell
codex plugin marketplace upgrade aicad-agent
codex plugin add aicad-agent@aicad-agent
```

卸载：

```powershell
codex plugin remove aicad-agent
```

## Release 压缩包

从 GitHub Releases 下载 `aicad-agent-1.10.0.zip` 和 `SHA256SUMS`，先核对 SHA-256，再解压。

```powershell
Get-FileHash .\aicad-agent-1.10.0.zip -Algorithm SHA256
```

压缩包顶层目录为 `aicad-agent`，包含插件清单、MCP、技能、规则、脚本、测试、AutoCAD bundle 源和可选 SolidWorks 宿主源。

## Python 依赖

基础 2D 编译只需要 Python 标准库。结构合同验证使用 `jsonschema`；包装 DXF、预览和拓扑 QA 还使用 `ezdxf`、`Pillow` 与 `Shapely`。统一安装命令：

```powershell
python -m pip install -r agent-plugin/aicad-agent/requirements-packaging.txt
```

## 默认不需要 API Key

推荐工作流由当前 Agent 编写 AICAD 计划，本地插件负责验证和编译，不需要 `OPENAI_API_KEY`。只有显式启用外部自然语言 provider 时，才需要对应 provider 配置。

## AutoCAD

- 无 AutoCAD 也可生成 AICAD、SCR、DXF、审计和 manifest；
- DWG、XData 持久化和保存重开需要 AutoCAD 2025+；
- bundle 位于发布包的 `runtime/autocad`；
- 无宿主时不得把便携 DXF 推断为真实 AutoCAD 验收。

## SolidWorks

- 需要 Windows x64、.NET Framework 4.8、已授权 SolidWorks 2026；
- 默认包只分发 C# 宿主源，不分发厂商互操作 DLL；
- `build3d --no-execute` 可在无 SolidWorks 环境生成执行计划和审计；
- SLDPRT、STEP 与重开验证只能在真实宿主门禁中完成。

## 本地开发

```powershell
git clone https://github.com/JMET04/aicad-agent.git
cd aicad-agent
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B -m unittest discover -s agent-plugin/aicad-agent/tests -p "test_*.py" -v
./scripts/build-agent-plugin.ps1 -OutputDirectory release-ci -Version 1.10.0
python -B scripts/verify_release_package.py release-ci/aicad-agent
```

## 常见问题

### 线段能画出来，但为什么仍然失败？

线段几何正确不等于产品正确。整体产品类型、结构族、上下闭合、关键尺寸和主要功能必须先与用户契约一致；之后还要通过独立秩、拓扑、功能面和参数域检查。

### 为什么不允许图片决定尺寸？

图片可以帮助理解拓扑和外观，但透视、缩放和裁剪使像素不是工程尺寸权威。尺寸必须来自用户数据、设计结果、正式目录或声明的计算公式。

### 为什么修改器只生成审阅草案？

线段关系可能影响多个面和工艺区。修改器先记录老师选择，再由 Agent 重新求解并运行全部门禁，避免一次点击绕过全局验证。

### 为什么发布状态仍是 review-only？

插件证明的是已建模约束与规则，不替代材料试验、设备能力、工艺公差和负责工程师签字。
