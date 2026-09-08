# 中国Wind基金分类 - ChinaMutualFundSector


简介


<table><tr><td>所属数据库:</td><td>中国共同基金数据库</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>共同基金-基础信息</td><td>数据披露频率:</td><td>日</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>日内</td></tr><tr><td>数据范围:</td><td>覆盖上海、深圳、场外公募基金</td><td>数据传输时间:</td><td>00:30,04:30,08:30,15:30,16:30,20:30,22:30</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>全部记录数:</td><td>93.99万</td></tr><tr><td>产品说明:</td><td>记录基金的Wind分类信息</td><td>数据包大小:</td><td>76 MB/年</td></tr></table>

# 数据字典


业务主键： Wind代码 , 所属板块 , 起始日期


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>Wind代码</td><td>F_INFO_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustomCode</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>2</td><td>所属板块</td><td>S_INFO_SECTOR</td><td>VARCHAR2(40)</td><td>AShareIndustriesCode</td><td>100.00%</td><td>关联AShareIndustriesCode表INDUSTRIESCODE字段,指向INDUSTRIESNAME字段2001开头为Wind基金分类板块;2003开头为银河基金分类板块(20170701起不再提供银河基金分类数据)</td></tr><tr><td>3</td><td>起始日期</td><td>S_INFO_SECTORENTRYDT</td><td>VARCHAR2(8)</td><td></td><td>99.00%</td><td>公司加入指定板块代码的生效日期;品种被纳入板块成份的日期;判断基金划分进入此版块类别的开始时间;记录公司或证券所属板块的板块起始生效日期;</td></tr><tr><td>4</td><td>截止日期</td><td>S_INFO_SECTOREXITDT</td><td>VARCHAR2(8)</td><td></td><td>64.00%</td><td>公司退出指定板块代码的生效日期;品种从板块成份中剔除的日期;判断基金划分进入此版块类别的终止时间;记录公司或证券所属板块的板块终止失效日期;</td></tr><tr><td>5</td><td>最新标志</td><td>CUR_SIGN</td><td>VARCHAR2(10)</td><td></td><td>100.00%</td><td>公司是否属于某个板块代码;值为1,则该条记录为当前板块成份;值为0,则该条记录为历史记录;判断本条数据是否是最新的数据;记录公司或证券所属板块是否为最新;最新标志,值为1,则该条记录为当前板块成份;值为0,则该条记录为历史记录;</td></tr><tr><td>6</td><td>证券ID</td><td>SEC_ID</td><td>VARCHAR2(10)</td><td>WindCustomCode</td><td>100.00%</td><td>万得自定义的能够标识证券的老编码</td></tr><tr><td>7</td><td>基金场内代码</td><td>S_INFO_INNERODE</td><td>VARCHAR2(40)</td><td>WindCustomCode</td><td>10.00%</td><td>基金在场内交易的交易代码</td></tr><tr><td>8</td><td>基金场外代码</td><td>S_INFO_OUTERODE</td><td>VARCHAR2(40)</td><td>WindCustomCode</td><td>100.00%</td><td>基金在场外交易的交易代码</td></tr><tr><td>9</td><td>所属板块代码(新)</td><td>S_INFO_SECTORN</td><td>VARCHAR2(40)</td><td>AShareIndustriesCode</td><td>100.00%</td><td>用于记录万得自定义的记录公司或证券所属板块的板块代码</td></tr></table>