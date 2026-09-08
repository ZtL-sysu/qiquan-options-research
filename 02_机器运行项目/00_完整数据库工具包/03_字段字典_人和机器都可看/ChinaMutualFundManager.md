# 中国共同基金基金经理 - ChinaMutualFundManager


简介


<table><tr><td>所属数据库:</td><td>中国共同基金数据库</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>共同基金-基础信息</td><td>数据披露频率:</td><td>日</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>日内</td></tr><tr><td>数据范围:</td><td>覆盖上海、深圳、场外公募基金</td><td>数据传输时间:</td><td>00:30,04:30,08:30,15:30,16:30,20:30,22:30</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>全部记录数:</td><td>7.64万</td></tr><tr><td>产品说明:</td><td>记录基金对应的基金经理信息</td><td>数据包大小:</td><td>3MB/年</td></tr></table>

# 数据字典


业务主键： Wind代码 , 姓名 , 任职日期


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>证券ID</td><td>SEC_ID</td><td>VARCHAR2(10)</td><td>WindCustomCod e</td><td>100.00%</td><td>万得自定义的能够标识证券的老编码</td></tr><tr><td>2</td><td>Wind代码</td><td>F_INFO_WIND_CODE</td><td>VARCHAR2(40)</td><td>WindCustomCod e</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>3</td><td>基金场内代码</td><td>S_INFO_INNE_RCODE</td><td>VARCHAR2(40)</td><td>WindCustomCod e</td><td>8.00%</td><td>基金在场内交易的交易代码</td></tr><tr><td>4</td><td>基金场外代码</td><td>S_INFO_OUTE_RCODE</td><td>VARCHAR2(40)</td><td>WindCustomCod e</td><td>100.00%</td><td>基金在场外交易的交易代码</td></tr><tr><td>5</td><td>公告日期</td><td>ANN_DATE</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>公告发布当天的日期</td></tr><tr><td>6</td><td>姓名</td><td>F_INFO_FUND_MANAGER</td><td>VARCHAR2(40)</td><td></td><td>100.00%</td><td>基金经理的姓名</td></tr><tr><td>7</td><td>性别</td><td>F_INFO_MAN_AGER_GENDE_R</td><td>VARCHAR2(10)</td><td>枚举类型</td><td>100.00%</td><td>m:男 f:女</td></tr><tr><td>8</td><td>出身年份</td><td>F_INFO_MAN_AGER_BIRTHY_EAR</td><td>VARCHAR2(10)</td><td></td><td>8.00%</td><td>基金经理的出生年月</td></tr><tr><td>9</td><td>学历</td><td>F_INFO_MAN_AGER_EDUCA_TION</td><td>VARCHAR2(20)</td><td></td><td>99.00%</td><td>基金经理接受教育的最高水平</td></tr><tr><td>10</td><td>国籍</td><td>F_INFO_MAN_AGER_NATIO_NALITY</td><td>VARCHAR2(10)</td><td>Countryandareac ode</td><td>100.00%</td><td>基金经理属于某一个国家的国民或公民的法律资格</td></tr><tr><td>11</td><td>任职日期</td><td>F_INFO_MAN_AGER_START_DATE</td><td>VARCHAR2(8)</td><td></td><td>99.00%</td><td>担任某只基金产品基金经理职位的日期</td></tr><tr><td>12</td><td>离职日期</td><td>F_INFO_MAN_AGER_LEAVE_DATE</td><td>VARCHAR2(8)</td><td></td><td>55.00%</td><td>离任某只基金产品基金经理职位的日期</td></tr><tr><td>13</td><td>简历</td><td>F_INFO_MAN_AGER_RESUM_E</td><td>CLOB</td><td></td><td>100.00%</td><td>基金经理教育、工作经历</td></tr><tr><td>14</td><td>基金经理id</td><td>F_INFO_FUND_MANAGER_ID</td><td>VARCHAR2(10)</td><td></td><td>100.00%</td><td>基金经理在万得库中对应的唯一标识ID</td></tr><tr><td>15</td><td>职务</td><td>S_INFO_MAN_AGER_POST</td><td>VARCHAR2(200)</td><td></td><td>3.00%</td><td>对基金经理代为履职事件的补充说明</td></tr><tr><td>16</td><td>代管基金经理</td><td>F_INFO_ESSCR_OW_FUNDMA_NAGER</td><td>VARCHAR2(50)</td><td></td><td>3.00%</td><td>基金经理因故暂离岗,代为履职的基金经理</td></tr><tr><td>17</td><td>代管起始日期</td><td>F_INFO_ESSCR_OW_STARTD_ATE</td><td>VARCHAR2(8)</td><td></td><td>3.00%</td><td>基金经理因故暂离岗,代管基金经理的代管起始日期</td></tr><tr><td>18</td><td>代管结束日期</td><td>F_INFO_ESCR_OW_LEAVEDA_TE</td><td>VARCHAR2(8)</td><td></td><td>2.00%</td><td>基金经理因故暂离岗，代管基金
经理的代管结束日期</td></tr><tr><td>19</td><td>展示序号</td><td>F_INFO_DIS_S_ERIAL_NUMB_ER</td><td>NUMBER(2,
0)</td><td></td><td>44.00%</td><td>当前在职基金经理按照任职先后
顺序进行的编号</td></tr></table>