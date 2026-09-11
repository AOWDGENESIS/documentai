<div align="center">

<img src="docs/screenshots/logo.png" width="110" alt="DocumentAI 标志"/>

# DocumentAI

**本地文档智能 —— 分析 PDF、识别并填写表单、添加批注。完全离线。**

语言 / Languages / Языки / Langues：
[Deutsch](README.md) | [English](README.en.md) | [Русский](README.ru.md) | [Français](README.fr.md) | **中文**

![版本](https://img.shields.io/badge/版本-1.9.1-1473e6)
![平台](https://img.shields.io/badge/平台-Windows%2010%2F11-0078d4)
![Python](https://img.shields.io/badge/Python-3.12-3776ab)
![离线](https://img.shields.io/badge/100%25-离线-2e7d32)
![许可证](https://img.shields.io/badge/许可证-MIT-yellow)

</div>

---

## DocumentAI 是什么？

DocumentAI 是一款面向 PDF 文档的桌面应用：它可以**分析**文档、
**自动识别表单字段**、**填写表单**、提供 **40 多种**批注与编辑
**工具**、**对比**版本、**导出**为 Office 格式，并将个人资料数据
保存在**本地加密保险库**中 —— 全程无需云端、无需账户、无遥测。

工具集对标 **Adobe Acrobat Reader DC（专业版）** 的功能范围 ——
完全在本地离线重建，无需订阅，也无需许可证密钥。

## 功能

### 表单字段识别
- **行对模型**：标签在上，输入线在下 —— 输入的文字**恰好落在
  线上**，就像手写一样
- 网格与表格：空白单元格自动成为字段；列标题（例如星期几）
  成为带有清晰标签的复选框
- 类型识别：日期、电话、电子邮箱、邮政编码、IBAN、签名、数字、文本
- 通过绘制的方框和字符识别复选框
- 如有需要，识别出的字段可以用**鼠标移动**重新定位

### 工具（45 种）
选择、平移、插入文本框、打叉/打钩/画点、圈选、高亮、下划线、
删除线、便签、附加文件、自由手绘、直线、箭头、圆、矩形、
多边形、折线、批注气泡、文本标注、测量对象、插入文本、插入
图片、链接、水印、页眉页脚、Bates 编号、背景色、涂黑（脱敏）、
受保护保存、签名、认证副本、页面管理（删除、旋转、移动、合并）、
格式转换（Word、Excel、PowerPoint、文本、RTF）、打印、图章、
字段识别、删除字段、移动字段、边界框 —— 每个工具都有**专属图标**，
并在状态栏中显示说明。

### OCR（光学字符识别）
使用 **Tesseract**（德语+英语）读取扫描件。预处理（灰度化、
2 倍放大、自动对比度）提高了对小型标签的识别率；扫描结构分析
即使在没有文本层的情况下也能找到字段线和方框。

### 数据与隐私
- 基于个人资料数据（家庭成员）**自动填充**，带置信度显示和校验
- **数据保险库**：本地加密（AES-256-GCM），主密码可选保存在
  Windows 凭据管理器中
- **版本管理**：“保存新版本”、撤销/重做、版本对比（文本差异、
  字段差异、图像化视觉对比）
- **导出**：Word (.docx)、Excel (.xlsx)、PowerPoint (.pptx)、文本、RTF
- **完全本地化**：没有云端，不需要网络连接，文档内容绝不离开
  您的电脑

### 界面
- Acrobat 风格布局：工具栏、页面缩略图、导航、属性面板
- **浅色与深色主题**（一键切换；自动记住选择）
- 鼠标滚轮滚动、缩放、就地编辑（点击字段，Esc 结束）

![DocumentAI 浅色主题](docs/screenshots/app-hell.png)
*字段识别：输入的文字位于输入线上。*

![DocumentAI 深色主题](docs/screenshots/app-dunkel.png)
*深色主题。*

![工具](docs/screenshots/werkzeuge.png)
*带图标的工具箱。*

## 安装（Windows）

1. 从[发布页面](../../releases)下载压缩包
   `DocumentAI-Installer_…_v18_1.9.1.zip`
2. 解压（右键 →“全部解压缩”）
3. 双击 `DocumentAI-installieren.bat`

就这么简单。安装程序自带独立的 Python 运行环境和全部依赖库 ——
**无需管理员权限，无需联网**。旧的安装和快捷方式会被自动清理
（用户数据予以保留）。

## 从源码安装

环境要求：Python 3.10+（测试环境：3.12）；OCR 功能可选安装
Tesseract。

```bash
pip install -r requirements.txt
python DocumentAI.py            # 图形界面
python DocumentAI.py --cli …    # 命令行模式
python DocumentAI.py --selbsttest
```

如需 OCR，请另外安装 Tesseract 可执行文件（Windows：UB-Mannheim
构建版本；Debian/Ubuntu：`tesseract-ocr tesseract-ocr-deu`）。
没有 Tesseract 时其他一切功能正常运行 —— OCR 功能会优雅降级并
给出明确提示。

## 架构

| 模块 | 职责 |
|---|---|
| `documentai/engines/field_detector.py` | 可视化表单字段识别（行对、网格、输入带、间隙、方框） |
| `documentai/engines/semantic.py` | 类型与规范名称识别（德语复合词） |
| `documentai/engines/ocr.py` | 带预处理的 Tesseract 集成 |
| `documentai/engines/annotate.py` | 批注（高亮、绘图、图章、涂黑……） |
| `documentai/engines/exporter.py` | 导出/导入（docx、xlsx、pptx、txt、rtf） |
| `documentai/engines/compare.py` | 文本、字段与视觉对比 |
| `documentai/engines/signatures.py` | 签名分析、签署（pyhanko） |
| `documentai/services/` | 分析服务、个人资料、保险库、工具查找 |
| `documentai/gui/` | tkinter 界面、主题（浅色/深色）、面板 |
| `documentai/bilder/symbole.py` | 本地绘制的工具图标 |
| `tests/` | 249 项测试（字段识别、图形界面、流水线、导出、保险库……） |

## 测试

```bash
python -m pytest tests/ -q
```

- **249 项主机测试**（单元测试 + Xvfb 下的界面测试）
- **Windows 实验室**：Wine 下的完整测试套件
- **全新安装验证**：安装程序 → 安装 → 冒烟测试 → 界面测试，
  全自动完成

## 自行构建安装程序

Windows 安装程序在 Linux 上通过 Wine 构建：

```bash
bash winenv/rebuild-windows-lab.sh   # 搭建 Wine 实验室
bash winenv/build-installer-v5.sh    # 构建安装程序压缩包
bash winenv/verify-windows.sh        # 验证安装
```

## 文档

- [更新日志](CHANGELOG.md) —— 所有版本
- [测试报告](docs/TESTBERICHT.md) —— 完整的验证历史（德语）
- [安装程序指南](docs/LIESMICH.txt) —— 随附的安装说明（德语）

## 安全与隐私

参见 [SECURITY.md](SECURITY.md)。简而言之：所有处理均在本地完成；
数据保险库采用 AES-256-GCM 加密；“受保护保存”可生成带密码的
PDF（AES-256）；涂黑（脱敏）会永久删除内容。

## 参与贡献

参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE) —— 版权所有 © 2026 DocumentAI。

---

<div align="center">

**DocumentAI —— 您的文档始终属于您。**

</div>
