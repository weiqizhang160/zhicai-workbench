# -*- coding: utf-8 -*-
"""小企业会计准则科目模板（项目书 6.6）。

条目结构：(code, name, account_type, direction, parent_code, auxiliary_flags)
- direction: debit(借方余额) / credit(贷方余额)
- auxiliary_flags: None 或 '{"partner": true}'（往来核算）
- is_leaf 由初始化服务按父子关系自动判定（有子科目的不是末级）
"""

COA_SMALL = [
    # ============ 资产类 ============
    ("1001", "库存现金", "asset_current", "debit", None, None),
    ("1002", "银行存款", "asset_current", "debit", None, None),
    ("1012", "其他货币资金", "asset_current", "debit", None, None),
    ("1101", "短期投资", "asset_current", "debit", None, None),
    ("1121", "应收票据", "asset_current", "debit", None, '{"partner": true}'),
    ("1122", "应收账款", "asset_current", "debit", None, '{"partner": true}'),
    ("1123", "预付账款", "asset_current", "debit", None, '{"partner": true}'),
    ("1131", "应收股利", "asset_current", "debit", None, None),
    ("1132", "应收利息", "asset_current", "debit", None, None),
    ("1221", "其他应收款", "asset_current", "debit", None, '{"partner": true}'),
    ("1231", "坏账准备", "asset_current", "credit", None, None),
    ("1401", "材料采购", "asset_current", "debit", None, None),
    ("1403", "原材料", "asset_current", "debit", None, None),
    ("1405", "库存商品", "asset_current", "debit", None, None),
    ("1471", "存货跌价准备", "asset_current", "credit", None, None),
    ("1501", "长期债券投资", "asset_fixed", "debit", None, None),
    ("1601", "固定资产", "asset_fixed", "debit", None, None),
    ("1602", "累计折旧", "asset_depreciation", "credit", None, None),
    ("1604", "在建工程", "asset_fixed", "debit", None, None),
    ("1605", "工程物资", "asset_fixed", "debit", None, None),
    ("1606", "固定资产清理", "asset_fixed", "debit", None, None),
    ("1701", "无形资产", "other", "debit", None, None),
    ("1702", "累计摊销", "asset_depreciation", "credit", None, None),
    ("1801", "长期待摊费用", "other", "debit", None, None),
    ("1901", "待处理财产损溢", "other", "debit", None, None),
    # ============ 负债类 ============
    ("2001", "短期借款", "liability_current", "credit", None, None),
    ("2201", "应付票据", "liability_current", "credit", None, '{"partner": true}'),
    ("2202", "应付账款", "liability_current", "credit", None, '{"partner": true}'),
    ("2203", "预收账款", "liability_current", "credit", None, '{"partner": true}'),
    ("2211", "应付职工薪酬", "liability_current", "credit", None, None),
    ("2211.01", "工资", "liability_current", "credit", "2211", None),
    ("2211.02", "社保公积金", "liability_current", "credit", "2211", None),
    ("2221", "应交税费", "liability_current", "credit", None, None),
    ("2221.01", "应交增值税", "liability_current", "credit", "2221", None),
    ("2221.01.01", "销项税额", "liability_current", "credit", "2221.01", None),
    ("2221.01.02", "进项税额", "liability_current", "credit", "2221.01", None),
    ("2221.01.03", "已交税金", "liability_current", "credit", "2221.01", None),
    ("2221.01.04", "转出未交增值税", "liability_current", "credit", "2221.01", None),
    ("2221.02", "未交增值税", "liability_current", "credit", "2221", None),
    ("2221.03", "应交企业所得税", "liability_current", "credit", "2221", None),
    ("2221.04", "应交个人所得税", "liability_current", "credit", "2221", None),
    ("2221.05", "应交印花税", "liability_current", "credit", "2221", None),
    ("2221.06", "应交城建税", "liability_current", "credit", "2221", None),
    ("2221.07", "应交教育费附加", "liability_current", "credit", "2221", None),
    ("2221.08", "应交地方教育附加", "liability_current", "credit", "2221", None),
    ("2221.10", "应交出口退税", "liability_current", "credit", "2221", None),
    ("2231", "应付利息", "liability_current", "credit", None, None),
    ("2232", "应付利润", "liability_current", "credit", None, None),
    ("2241", "其他应付款", "liability_current", "credit", None, '{"partner": true}'),
    ("2401", "递延收益", "liability_current", "credit", None, None),
    ("2501", "长期借款", "liability_long", "credit", None, None),
    ("2701", "长期应付款", "liability_long", "credit", None, None),
    # ============ 权益类 ============
    ("3001", "实收资本", "equity", "credit", None, None),
    ("3002", "资本公积", "equity", "credit", None, None),
    ("3101", "盈余公积", "equity", "credit", None, None),
    ("3103", "本年利润", "equity", "credit", None, None),
    ("3104", "利润分配", "equity", "credit", None, None),
    # ============ 成本类 ============
    ("5001", "生产成本", "cost", "debit", None, None),
    ("5101", "制造费用", "cost", "debit", None, None),
    ("5201", "劳务成本", "cost", "debit", None, None),
    # ============ 损益类-收入 ============
    ("6001", "主营业务收入", "revenue", "credit", None, '{"partner": true}'),
    ("6051", "其他业务收入", "revenue", "credit", None, None),
    ("6111", "投资收益", "revenue", "credit", None, None),
    ("6301", "营业外收入", "revenue", "credit", None, None),
    # ============ 损益类-费用 ============
    ("6401", "主营业务成本", "expense", "debit", None, None),
    ("6402", "其他业务成本", "expense", "debit", None, None),
    ("6403", "税金及附加", "expense", "debit", None, None),
    ("6601", "销售费用", "expense", "debit", None, None),
    ("6601.01", "工资", "expense", "debit", "6601", None),
    ("6601.02", "社保公积金", "expense", "debit", "6601", None),
    ("6601.03", "广告宣传费", "expense", "debit", "6601", None),
    ("6601.04", "运输物流费", "expense", "debit", "6601", None),
    ("6602", "管理费用", "expense", "debit", None, None),
    ("6602.01", "办公费", "expense", "debit", "6602", None),
    ("6602.02", "差旅费", "expense", "debit", "6602", None),
    ("6602.03", "业务招待费", "expense", "debit", "6602", None),
    ("6602.04", "房租", "expense", "debit", "6602", None),
    ("6602.05", "水电物业费", "expense", "debit", "6602", None),
    ("6602.06", "通讯网络费", "expense", "debit", "6602", None),
    ("6602.07", "工资", "expense", "debit", "6602", None),
    ("6602.08", "社保公积金", "expense", "debit", "6602", None),
    ("6602.09", "折旧费", "expense", "debit", "6602", None),
    ("6603", "财务费用", "expense", "debit", None, None),
    ("6603.01", "利息支出", "expense", "debit", "6603", None),
    ("6603.02", "手续费", "expense", "debit", "6603", None),
    ("6711", "营业外支出", "expense", "debit", None, None),
    ("6801", "所得税费用", "expense", "debit", None, None),
]

# 企业会计准则模板 M2+ 再提供，先映射到小企业模板占位（README 登记假设）
COA_ENTERPRISE = COA_SMALL

# 默认账簿（凭证字）：记 / 收 / 付 / 转
DEFAULT_JOURNALS = [
    ("记", "记账凭证", "general"),
    ("收", "收款凭证", "receipt"),
    ("付", "付款凭证", "payment"),
    ("转", "转账凭证", "transfer"),
]
