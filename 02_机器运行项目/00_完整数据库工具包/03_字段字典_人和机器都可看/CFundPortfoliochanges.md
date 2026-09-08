# 中国共同基金投资组合重大变动(报告期) - CFundPortfoliochanges


简介


<table><tr><td>所属数据库:</td><td>中国共同基金数据库</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>共同基金-投资组合</td><td>数据披露频率:</td><td>季</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>日内</td></tr><tr><td>数据范围:</td><td>覆盖上海、深圳、场外公募基金</td><td>数据传输时间:</td><td>00:30,04:30,08:30,15:30,16:30,20:30</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>年更新记录数:</td><td>84.98万/年</td></tr><tr><td>产品说明:</td><td>记录基金定期（季度）公布的投资组合重大变动信息</td><td>数据包大小:</td><td>81 MB/年</td></tr></table>

# 数据字典


业务主键： 基金万得代码 , 报告期 , 股票代码 , 变动类型


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>基金证券ID</td><td>SEC_ID</td><td>VARCHAR2(10)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的能够标识证券的老编码</td></tr><tr><td>2</td><td>基金万得代码</td><td>F_INFO_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>3</td><td>基金场内代码</td><td>S_INFO_INNERCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>9.00%</td><td>基金在场内交易的交易代码</td></tr><tr><td>4</td><td>基金场外代码</td><td>S_INFO_OUTERCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>基金在场外交易的交易代码</td></tr><tr><td>5</td><td>公告日期</td><td>ANN_DT</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>数据来源材料的披露日期</td></tr><tr><td>6</td><td>报告期</td><td>REPORTPERIOD</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>基金当前定期报告区间的截止时间</td></tr><tr><td>7</td><td>股票代码</td><td>S_INFO_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>8</td><td>变动类型</td><td>CHANGE_TYPE</td><td>VARCHAR2(10)</td><td></td><td>100.00%</td><td>基金投资的股票调仓的方式</td></tr><tr><td>9</td><td>累计变动金额</td><td>ACCUMULATEDA</td><td>NUMBER(20,4)</td><td></td><td>100.00%</td><td>基金投资的股票调仓的金额</td></tr><tr><td>10</td><td>累计变动金额占期初净资产比例</td><td>BEGIN_NET_ASET_RATIO</td><td>NUMBER(20,4)</td><td></td><td>90.00%</td><td>基金投资的股票调仓的金额占该基金期初资产净值的比例</td></tr></table>