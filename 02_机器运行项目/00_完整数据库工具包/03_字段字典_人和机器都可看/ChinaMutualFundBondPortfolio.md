# 中国共同基金投资组合— 持券明细 - ChinaMutualFundBondPortfolio


简介


<table><tr><td>所属数据库:</td><td>中国共同基金数据库</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>共同基金-投资组合</td><td>数据披露频率:</td><td>日</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>日内</td></tr><tr><td>数据范围:</td><td>覆盖上海、深圳、场外公募基金</td><td>数据传输时间:</td><td>00:30,04:30,08:30,12:00,15:30,16:30,20:30,22:30</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>年更新记录数:</td><td>61.06万/年</td></tr><tr><td>产品说明:</td><td>记录基金定期（季度）公布的持券明细</td><td>数据包大小:</td><td>11MB/年</td></tr></table>

# 数据字典


业务主键： 基金Wind代码 , 截止日期 , 持有债券Wind代码


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>基金Wind代码</td><td>S_INFO_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>2</td><td>截止日期</td><td>F_PRT_ENDDATE</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>统计当前基金持仓明细数据的日期</td></tr><tr><td>3</td><td>货币代码</td><td>CRNCY_CODE</td><td>VARCHAR2(10)</td><td>Currencycode</td><td>99.00%</td><td>计量持仓市值所使用的的币种</td></tr><tr><td>4</td><td>持有债券Wind代码</td><td>S_INFO_BONDWINDCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>5</td><td>持有债券市值(元)</td><td>F_PRT_BDVALUE</td><td>NUMBER(20,4)</td><td></td><td>99.00%</td><td>基金持有对应有价证券的价值金额</td></tr><tr><td>6</td><td>持有债券数量(张)</td><td>F_PRT_BDQUANTITY</td><td>NUMBER(20,4)</td><td></td><td>57.00%</td><td>基金持有对应有价证券的数量</td></tr><tr><td>7</td><td>持有债券市值占基金净值比例(%)</td><td>F_PRT_BDVALUETONAV</td><td>NUMBER(20,4)</td><td></td><td>99.00%</td><td>基金持有对应有价证券的价值金额占该基金资产净值的比例</td></tr><tr><td>8</td><td>公告日期</td><td>F_ANN_DATE</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>当前基金持仓明细数据来源材料的披露日期</td></tr><tr><td>9</td><td>非公开发行股数</td><td>NUMB_NP_OSX</td><td>NUMBER(20,4)</td><td></td><td>0.00%</td><td>不在公开市场自由流通的股票数量</td></tr><tr><td>10</td><td>非公开发行股期末均价</td><td>AVRG_CLSPRIICE_NPOS</td><td>NUMBER(20,4)</td><td></td><td>0.00%</td><td>不在公开市场自由流通的股票本报告期末的平均价格</td></tr><tr><td>11</td><td>基金证券ID</td><td>SEC_ID</td><td>VARCHAR2(10)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的能够标识证券的老编码</td></tr><tr><td>12</td><td>基金场内代码</td><td>S_INFO_INNERCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>4.00%</td><td>基金在场内交易的交易代码</td></tr><tr><td>13</td><td>基金场外代码</td><td>S_INFO_OUTERCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>基金在场外交易的交易代码</td></tr></table>