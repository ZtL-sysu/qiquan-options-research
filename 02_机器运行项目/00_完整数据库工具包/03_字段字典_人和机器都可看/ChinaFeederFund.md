# 中国联接基金基本资料 - ChinaFeederFund


简介


<table><tr><td>所属数据库:</td><td>中国共同基金数据库</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>共同基金-基础信息</td><td>数据披露频率:</td><td>日</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>日内</td></tr><tr><td>数据范围:</td><td>覆盖上海、深圳、场外公募基金</td><td>数据传输时间:</td><td>00:30,04:30,08:30,15:30,16:30,20:30,22:30</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>全部记录数:</td><td>0.21万</td></tr><tr><td>产品说明:</td><td>记录联接基金的基本资料</td><td>数据包大小:</td><td>1 MB/年</td></tr></table>

# 数据字典


业务主键： 联接基金指数Wind代码


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>联接基金指数证券ID</td><td>SEC_ID1</td><td>VARCHAR2(10)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码；证券产品在万得库中对应的唯一标识ID；万得定义的用来识别证券的内部唯一编码；</td></tr><tr><td>2</td><td>联接基金指数Wind代码</td><td>S_INFO_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>同时在场内场外交易的基金，只展示场内代码。如：510050.SH</td></tr><tr><td>3</td><td>联接基金证券ID</td><td>SEC_ID2</td><td>VARCHAR2(10)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的能够标识证券的老编码</td></tr><tr><td>4</td><td>联接基金Wind代码</td><td>F_INFO_FEEDER_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>5</td><td>被联接基金证券ID</td><td>SEC_ID3</td><td>VARCHAR2(10)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的能够标识证券的老编码</td></tr><tr><td>6</td><td>被联接基金Wind代码</td><td>F_INFO_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr></table>