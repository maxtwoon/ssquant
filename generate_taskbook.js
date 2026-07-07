/**
 * 缠论策略最终验证任务书 v3.0 生成脚本
 * 运行方式：
 *   npm install -g docx   （首次需安装，已安装可跳过）
 *   node generate_taskbook.js
 * 输出文件：缠论策略最终验证任务书_v3.0.docx
 */

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  Header, Footer, PageNumber, VerticalAlign, LevelFormat,
} = require("docx");
const fs = require("fs");

// ─── 颜色常量 ─────────────────────────────────────────────────
const COLOR_HEADING  = "1F3864";   // 深蓝
const COLOR_ACCENT   = "2E75B6";   // 中蓝（表头底色）
const COLOR_LIGHT    = "D9E2F3";   // 浅蓝（隔行）
const COLOR_WHITE    = "FFFFFF";
const COLOR_BODY     = "2F2F2F";   // 正文深灰
const COLOR_WARN     = "C00000";   // 红色（警告）
const COLOR_BORDER   = "BFBFBF";

// ─── 辅助函数 ──────────────────────────────────────────────────
function cell(text, opts = {}) {
  const {
    bold = false, italic = false, color = COLOR_BODY,
    fill = COLOR_WHITE, size = 20, align = AlignmentType.LEFT,
    width = 3120,
  } = opts;
  const border = { style: BorderStyle.SINGLE, size: 1, color: COLOR_BORDER };
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: { fill, type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    borders: { top: border, bottom: border, left: border, right: border },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      alignment: align,
      children: [new TextRun({ text, bold, italic, color, size, font: "Arial" })],
    })],
  });
}

function headerCell(text, width = 3120) {
  return cell(text, { bold: true, fill: COLOR_ACCENT, color: COLOR_WHITE, width });
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 300, after: 120 },
    children: [new TextRun({ text, bold: true, size: 28, color: COLOR_HEADING, font: "Arial" })],
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 80 },
    children: [new TextRun({ text, bold: true, size: 24, color: COLOR_ACCENT, font: "Arial" })],
  });
}

function body(text, opts = {}) {
  const { bold = false, color = COLOR_BODY, spacing = { before: 60, after: 60 } } = opts;
  return new Paragraph({
    spacing,
    children: [new TextRun({ text, bold, color, size: 20, font: "Arial" })],
  });
}

function warn(text) {
  return new Paragraph({
    spacing: { before: 60, after: 60 },
    children: [new TextRun({ text: "⚠ " + text, bold: true, color: COLOR_WARN, size: 20, font: "Arial" })],
  });
}

function bullet(text, bold = false) {
  return new Paragraph({
    spacing: { before: 40, after: 40 },
    indent: { left: 360, hanging: 200 },
    children: [
      new TextRun({ text: "• ", bold: true, color: COLOR_ACCENT, size: 20, font: "Arial" }),
      new TextRun({ text, bold, color: COLOR_BODY, size: 20, font: "Arial" }),
    ],
  });
}

function gap(sz = 120) {
  return new Paragraph({ spacing: { before: sz, after: 0 }, children: [] });
}

function rule() {
  return new Paragraph({
    spacing: { before: 60, after: 60 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: COLOR_ACCENT } },
    children: [],
  });
}

// ─── 表格构建器 ────────────────────────────────────────────────
function taskTable(rows, colWidths) {
  const totalWidth = colWidths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: totalWidth, type: WidthType.DXA },
    columnWidths: colWidths,
    rows,
  });
}

// ─── 主文档 ────────────────────────────────────────────────────
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 20, color: COLOR_BODY } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: COLOR_HEADING },
        paragraph: { spacing: { before: 300, after: 120 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: COLOR_ACCENT },
        paragraph: { spacing: { before: 240, after: 80 }, outlineLevel: 1 },
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },   // A4
        margin: { top: 1440, right: 1260, bottom: 1440, left: 1260 },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: COLOR_ACCENT } },
          children: [new TextRun({ text: "缠论策略最终验证任务书 v3.0", color: COLOR_ACCENT, size: 18, font: "Arial" })],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "第 ", color: COLOR_BODY, size: 18, font: "Arial" }),
            new TextRun({ children: [PageNumber.CURRENT], color: COLOR_BODY, size: 18, font: "Arial" }),
            new TextRun({ text: " 页  |  机密 · 仅限内部使用", color: COLOR_BODY, size: 18, font: "Arial" }),
          ],
        })],
      }),
    },
    children: [

      // ══ 封面标题区 ══════════════════════════════════════════
      gap(200),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 80 },
        children: [new TextRun({ text: "缠论策略最终验证任务书", bold: true, size: 52, color: COLOR_HEADING, font: "Arial" })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 40 },
        children: [new TextRun({ text: "v3.0  |  Hermes 执行版", size: 28, color: COLOR_ACCENT, font: "Arial" })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 0 },
        children: [new TextRun({ text: "编制：clma　　执行方：Hermes Agent　　审核状态：待执行", size: 18, color: "888888", font: "Arial" })],
      }),
      rule(),
      gap(60),

      // ══ 一、项目背景 ══════════════════════════════════════════
      h1("一、项目背景"),
      body("5分钟与1分钟周期测试均未获得稳定Alpha。5分钟信号稀疏且持续亏损，1分钟交易频率充足但Sharpe仍低（最高0.16），无过滤模式出现灾难性亏损。当前进入最终验证阶段，目标是判断缠论信号是否存在可持续交易价值，而非继续参数优化。"),

      // ══ 二、研究目标 ══════════════════════════════════════════
      gap(),
      h1("二、研究目标"),
      body("验证信号Alpha来源、方向正确性、多空归因、多周期有效性，并依据预定标准决定项目继续研发或正式终止。"),

      // ══ 三、Early Stop 规则 ═══════════════════════════════════
      gap(),
      h1("三、Early Stop 规则"),
      body("在执行完 Task-1 和 Task-2 后，若满足以下任一条件，直接跳过 Task-3 至 Task-6，进入 Task-7 输出终止结论："),
      gap(40),
      bullet("Task-1 中正向与反向版本 Expectancy 均 ≤ 0"),
      bullet("Task-2 中所有信号类型（TYPE1 / TYPE1B / TYPE3）的多空归因 Expectancy 均 ≤ 0"),
      gap(40),
      warn("Early Stop 触发时，Task-7 须注明触发原因及对应数据，不得留空。"),

      // ══ 四、Task-1 ════════════════════════════════════════════
      gap(),
      h1("四、Task-1  Reverse Signal Test"),
      h2("测试目的"),
      body("验证信号方向是否定义错误，而非参数优化。"),
      h2("内容"),
      body("对全部信号执行正向与反向交易对比，输出 Sharpe、ProfitFactor、Expectancy、SQN、MAR。"),
      h2("执行注意"),
      bullet("须保留趋势过滤（至少 MA 或 DC 趋势过滤）以防止灾难性亏损干扰方向判断"),
      bullet("反向测试时过滤方向须同步反转，确保正反向测试条件完全对称"),

      // ══ 五、Task-2 ════════════════════════════════════════════
      gap(),
      h1("五、Task-2  Long / Short Attribution"),
      h2("测试目的"),
      body("识别最优 Alpha 来源，而非寻找最优信号组合。"),
      h2("内容"),
      body("分别统计 TYPE1、TYPE1B、TYPE3 在多头方向和空头方向的胜率、盈亏比、Expectancy、交易次数。"),
      h2("额外要求"),
      body("须补充各信号类型在不同市场状态（单边上涨 / 单边下跌 / 震荡）下的分类表现，判断信号有效性是否依赖特定行情环境。"),

      // ══ 六、Task-3 ════════════════════════════════════════════
      gap(),
      h1("六、Task-3  ATR Scan"),
      h2("测试目的"),
      body("验证有效 ATR 区间是否存在，而非寻找最优 ATR 值。"),
      h2("内容"),
      body("扫描 ATR = 2.0 至 5.0（步长 0.5），记录每档 Sharpe、ProfitFactor、Expectancy。"),
      h2("结果解读原则"),
      bullet("若 Expectancy 在所有 ATR 档位均 ≤ 0，判定信号无效"),
      bullet("若存在连续有效区间（如 ATR 3.0–4.5 Expectancy 均为正），则作为后续 Walk Forward 的测试参数"),
      warn("禁止将 IS 最优 ATR 值直接带入 OOS 测试，须在 OOS 段独立验证。"),

      // ══ 七、Task-4 ════════════════════════════════════════════
      gap(),
      h1("七、Task-4  Expectancy Analysis"),
      body("在全部测试中统一输出以下机构级指标："),
      gap(40),
      taskTable([
        new TableRow({ children: [headerCell("指标", 2400), headerCell("说明", 7026)] }),
        new TableRow({ children: [cell("Expectancy", { width: 2400 }), cell("期望收益 / 风险单位", { width: 7026 })] }),
        new TableRow({ children: [cell("ProfitFactor", { width: 2400, fill: COLOR_LIGHT }), cell("总盈利 / 总亏损", { width: 7026, fill: COLOR_LIGHT })] }),
        new TableRow({ children: [cell("SQN", { width: 2400 }), cell("系统质量数（综合频率与质量）", { width: 7026 })] }),
        new TableRow({ children: [cell("Kelly", { width: 2400, fill: COLOR_LIGHT }), cell("理论最优仓位比例；若 ≤ 0 则策略无数学正期望，须作为终止依据", { width: 7026, fill: COLOR_LIGHT })] }),
        new TableRow({ children: [cell("MAR", { width: 2400 }), cell("年化收益 / 最大回撤", { width: 7026 })] }),
      ], [2400, 7026]),

      // ══ 八、Task-5 ════════════════════════════════════════════
      gap(),
      h1("八、Task-5  Walk Forward"),
      body("四段滚动验证，以 OOS（2025）段结论为主要判断依据："),
      gap(40),
      taskTable([
        new TableRow({ children: [headerCell("阶段", 2000), headerCell("时间段", 3000), headerCell("用途", 4426)] }),
        new TableRow({ children: [cell("Train", { width: 2000 }), cell("2022–2023", { width: 3000 }), cell("参数确定", { width: 4426 })] }),
        new TableRow({ children: [cell("Validation", { width: 2000, fill: COLOR_LIGHT }), cell("2024", { width: 3000, fill: COLOR_LIGHT }), cell("参数验证", { width: 4426, fill: COLOR_LIGHT })] }),
        new TableRow({ children: [cell("OOS", { width: 2000, bold: true }), cell("2025", { width: 3000, bold: true }), cell("主要判断依据", { width: 4426, bold: true })] }),
        new TableRow({ children: [cell("Forward", { width: 2000, fill: COLOR_LIGHT }), cell("2026 H1", { width: 3000, fill: COLOR_LIGHT }), cell("参考（样本量有限，置信度低）", { width: 4426, fill: COLOR_LIGHT })] }),
      ], [2000, 3000, 4426]),
      gap(40),
      warn("Forward 段仅约半年数据，结论不作为主要判断依据，须在报告中注明置信度限制。"),

      // ══ 九、Task-6 ════════════════════════════════════════════
      gap(),
      h1("九、Task-6  Multi-Timeframe Verification"),
      h2("测试目的"),
      body("验证多周期结构是否改变信号性质，而非寻找最优过滤参数。"),
      h2("内容"),
      body("15 分钟趋势过滤 + 1 分钟入场，验证多周期结构有效性。"),
      h2("未来函数警告"),
      warn("15 分钟趋势判断必须使用 15 分钟 K 线收盘时的数据，严禁使用当前 1 分钟 bar 的实时数据判断 15 分钟趋势状态。执行前须通过代码审查确认数据口径。"),

      // ══ 十、Task-7 ════════════════════════════════════════════
      gap(),
      h1("十、Task-7  Final Verdict"),
      body("必须输出 Verdict A / B / C，并提供完整证据链（含各 Task 关键指标数值）。不得在证据不足时跳过结论。"),
      gap(40),
      taskTable([
        new TableRow({ children: [headerCell("等级", 1600), headerCell("条件", 4600), headerCell("结论", 3226)] }),
        new TableRow({ children: [
          cell("Verdict A", { width: 1600, bold: true, color: "375623" }),
          cell("OOS Sharpe ≥ 0.50 且 PF ≥ 1.30 且 Expectancy > 0", { width: 4600 }),
          cell("继续研发，进入实盘验证准备", { width: 3226 }),
        ]}),
        new TableRow({ children: [
          cell("Verdict B", { width: 1600, bold: true, color: "7F6000", fill: COLOR_LIGHT }),
          cell("OOS Sharpe 0.30–0.50 且 Expectancy > 0", { width: 4600, fill: COLOR_LIGHT }),
          cell("条件性继续：须明确指出需满足哪项条件后方可推进", { width: 3226, fill: COLOR_LIGHT }),
        ]}),
        new TableRow({ children: [
          cell("Verdict C", { width: 1600, bold: true, color: COLOR_WARN }),
          cell("触发终止标准，或 OOS Sharpe < 0", { width: 4600 }),
          cell("正式关闭缠论CTA项目", { width: 3226 }),
        ]}),
      ], [1600, 4600, 3226]),

      // ══ 十一、终止标准 ════════════════════════════════════════
      gap(),
      h1("十一、项目终止标准"),
      body("满足以下任一条件，则正式关闭缠论CTA项目："),
      gap(40),
      bullet("条件 A（单独触发）：OOS 段 Sharpe < 0", true),
      bullet("条件 B（联合触发）：OOS 段 Sharpe < 0.30 且 ProfitFactor < 1.20 且 Expectancy ≤ 0", true),
      bullet("条件 C（数学层面）：Kelly 值 ≤ 0 且 Early Stop 规则触发", true),

      // ══ 十二、执行计划 ════════════════════════════════════════
      gap(),
      h1("十二、执行计划"),
      gap(40),
      taskTable([
        new TableRow({ children: [headerCell("时间", 1600), headerCell("任务", 3200), headerCell("说明", 4626)] }),
        new TableRow({ children: [cell("Day 1", { width: 1600 }), cell("Task-1、Task-2", { width: 3200 }), cell("完成后检查 Early Stop 条件", { width: 4626 })] }),
        new TableRow({ children: [cell("Day 2", { width: 1600, fill: COLOR_LIGHT }), cell("Task-3、Task-4", { width: 3200, fill: COLOR_LIGHT }), cell("ATR 扫描 + 指标体系输出", { width: 4626, fill: COLOR_LIGHT })] }),
        new TableRow({ children: [cell("Day 3", { width: 1600 }), cell("Task-5", { width: 3200 }), cell("Walk Forward 完整 4 段（耗时较长）", { width: 4626 })] }),
        new TableRow({ children: [cell("Day 4", { width: 1600, fill: COLOR_LIGHT }), cell("Task-6、Task-7", { width: 3200, fill: COLOR_LIGHT }), cell("多周期验证 + 最终结论输出", { width: 4626, fill: COLOR_LIGHT })] }),
      ], [1600, 3200, 4626]),

      // ══ 十三、交付物 ══════════════════════════════════════════
      gap(),
      h1("十三、交付物"),
      bullet("最终研究报告（含 Verdict 及证据链）"),
      bullet("全部回测结果（含 OOS 段独立结果文件）"),
      bullet("参数表（含 IS 最优值与 OOS 验证值对比）"),
      bullet("多空归因分析（按信号类型 × 市场状态）"),
      bullet("结论文档"),

      gap(200),
      rule(),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 120, after: 0 },
        children: [new TextRun({ text: "本文件为机密研究资料，仅限内部使用", size: 16, color: "888888", italic: true, font: "Arial" })],
      }),
    ],
  }],
});

// ─── 输出 ──────────────────────────────────────────────────────
Packer.toBuffer(doc).then((buffer) => {
  const outPath = "缠论策略最终验证任务书_v3.0.docx";
  fs.writeFileSync(outPath, buffer);
  console.log("✅ 文件已生成：" + outPath);
}).catch((err) => {
  console.error("❌ 生成失败：", err);
});
