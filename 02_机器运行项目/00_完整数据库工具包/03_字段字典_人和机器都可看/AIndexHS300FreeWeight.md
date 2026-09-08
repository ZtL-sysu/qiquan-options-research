# 中国A股指数月权重 - AIndexHS300FreeWeight


简介


<table><tr><td>所属数据库:</td><td>指数数据库</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>指数-股票类(第三方中证)</td><td>数据披露频率:</td><td>月</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>准实时</td></tr><tr><td>数据范围:</td><td>覆盖中证指数公司指数</td><td>数据传输时间:</td><td>10:00-22:00</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>年更新记录数:</td><td>921.91万/年</td></tr><tr><td>产品说明:</td><td>记录A股指数的月权重信息,包含沪深300、北证50、上证50等指数</td><td>数据包大小:</td><td>285 MB/年</td></tr></table>

# 数据字典


业务主键： 指数Wind代码 , 成份股Wind代码 , 交易日期


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>指数Wind代码</td><td>S_INFO_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustomCode</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>2</td><td>成份股Wind代码</td><td>S_CON_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustomCode</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>3</td><td>交易日期</td><td>TRADE_DT</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>指数权重日期;指数权重数据的公布日期;</td></tr><tr><td>4</td><td>权重</td><td>I_WEIGHT</td><td>NUMBER(20,4)</td><td></td><td>100.00%</td><td>指数成份在该指数所有成份中所占比重;某个指数在样本指数成份中占有的份额;</td></tr></table>