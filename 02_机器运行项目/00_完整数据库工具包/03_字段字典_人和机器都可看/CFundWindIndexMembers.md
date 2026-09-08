# 中国共同基金WIND指数最新成份明细 - CFundWindIndexMembers


简介


<table><tr><td>所属数据库:</td><td>指数数据库</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>指数-基金类指数数据(万得)</td><td>数据披露频率:</td><td>日</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>日内</td></tr><tr><td>数据范围:</td><td>覆盖上海、深圳交易所基金指数</td><td>数据传输时间:</td><td>00:30,04:30,08:30,15:30,16:30,20:30,22:30</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>全部记录数:</td><td>36.70万</td></tr><tr><td>产品说明:</td><td>记录基金WIND指数的最新成份明细</td><td>数据包大小:</td><td>27 MB/年</td></tr></table>

# 数据字典


业务主键： 板块代码 , 成份万得代码 , 纳入日期


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>板块代码</td><td>S_CON_CODE</td><td>VARCHAR2(16)</td><td></td><td>100.00%</td><td>万得自定义的用来识别板块成分的唯一编码</td></tr><tr><td>2</td><td>板块名称</td><td>S_CON_NAME</td><td>VARCHAR2(100)</td><td></td><td>100.00%</td><td>板块树结构中节点中文名称；板块的中文名称；当前板块所对应节点的中文名称；</td></tr><tr><td>3</td><td>成份万得代码</td><td>S_INFO_WIND_CODE</td><td>VARCHAR2(40)</td><td>WindCustomCod e</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码；板块成分对应的万得自定义的用来识别证券的唯一编码；</td></tr><tr><td>4</td><td>纳入日期</td><td>S_CON_INDATE</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>纳入或剔除板块的开盘前生效日期</td></tr><tr><td>5</td><td>剔除日期</td><td>S_CON_OUTDATE</td><td>VARCHAR2(8)</td><td></td><td>35.00%</td><td>纳入或剔除板块的开盘前生效日期</td></tr><tr><td>6</td><td>最新标志</td><td>CUR_SIGN</td><td>NUMBER(1,0)</td><td></td><td>100.00%</td><td>公司是否属于某个板块代码；值为1，则该条记录为当前板块成份；值为0，则该条记录为历史记录；判断本条数据是否是最新的数据；记录公司或证券所属板块是否为最新；最新标志，值为1，则该条记录为当前板块成份；值为0，则该条记录为历史记录；</td></tr><tr><td>7</td><td>成份证券ID</td><td>SEC_ID</td><td>VARCHAR2(10)</td><td>WindCustomCod e</td><td>100.00%</td><td>万得自定义的能够标识证券的老编码</td></tr><tr><td>8</td><td>基金场内代码</td><td>S_INFO_INNERCODE</td><td>VARCHAR2(40)</td><td>WindCustomCod e</td><td>10.00%</td><td>基金在场内交易的交易代码</td></tr><tr><td>9</td><td>基金场外代码</td><td>S_INFO_OUTERCODE</td><td>VARCHAR2(40)</td><td>WindCustomCod e</td><td>100.00%</td><td>基金在场外交易的交易代码</td></tr></table>