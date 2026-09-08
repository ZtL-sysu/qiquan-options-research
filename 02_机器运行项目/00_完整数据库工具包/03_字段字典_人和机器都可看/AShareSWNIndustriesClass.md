# 申万行业分类 - AShareSWNIndustriesClass


简介


<table><tr><td>所属数据库:</td><td>中国A股数据库</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>中国A股-第三方申万数据</td><td>数据披露频率:</td><td>日</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>准实时</td></tr><tr><td>数据范围:</td><td>覆盖上海、深圳、北京交易所的A股股票</td><td>数据传输时间:</td><td>15:30-次日 02:00</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>全部记录数:</td><td>0.80万</td></tr><tr><td>产品说明:</td><td>记录2021年最新发布的A股申万行业分类信息</td><td>数据包大小:</td><td>1 MB/年</td></tr></table>

# 数据字典


业务主键： Wind代码 , 申万行业代码 , 纳入日期


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>Wind代码</td><td>S_INFO_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustomCode</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>2</td><td>申万行业代码</td><td>SW_IND_CODE</td><td>VARCHAR2(50)</td><td>枚举类型</td><td>100.00%</td><td>万得自编的申万行业板块代码</td></tr><tr><td>3</td><td>纳入日期</td><td>ENTRY_DT</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>该公司申万行业的生效日期</td></tr><tr><td>4</td><td>剔除日期</td><td>REMOVE_DT</td><td>VARCHAR2(8)</td><td></td><td>27.00%</td><td>该公司申万行业的失效日期</td></tr><tr><td>5</td><td>最新标志</td><td>CUR_SIGN</td><td>VARCHAR2(10)</td><td></td><td>100.00%</td><td>1:是0:否</td></tr></table>