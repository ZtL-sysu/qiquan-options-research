# 中国共同基金份额 - ChinaMutualFundShare


简介


<table><tr><td>所属数据库:</td><td>中国共同基金数据库</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>共同基金-市场表现</td><td>数据披露频率:</td><td>日</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>日内</td></tr><tr><td>数据范围:</td><td>覆盖上海、深圳、场外公募基金</td><td>数据传输时间:</td><td>00:30,04:30,07:00,07:30,08:00,08:30,09:00,09:30,10:00,15:30,19:00</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>年更新记录数:</td><td>40.39万/年</td></tr><tr><td>产品说明:</td><td>记录交易所、基金公司公告公布的基金份额变动情况</td><td>数据包大小:</td><td>19 MB/年</td></tr></table>

# 数据字典


业务主键： Wind代码 , 截止日期


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>Wind代码</td><td>F_INFO_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>2</td><td>变动日期(废弃)</td><td>CHANGE_DATE</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>记录当前该基金份额数据的日期,其中对于深交所ETF代表盘前份额</td></tr><tr><td>3</td><td>基金总份额(万份)</td><td>F_UNIT_TOTAL</td><td>NUMBER(20,6)</td><td></td><td>100.00%</td><td>分级基金总份额</td></tr><tr><td>4</td><td>流通份额(万份)</td><td>F_INFO_SHARE</td><td>NUMBER(20,6)</td><td></td><td>77.00%</td><td>基金上市流通的份额</td></tr><tr><td>5</td><td>基金份额(万份)</td><td>FUNDSHARE</td><td>NUMBER(20,6)</td><td></td><td>100.00%</td><td>该基金的基金总份额</td></tr><tr><td>6</td><td>是否为合并数据</td><td>F_UNIT_MERGEDSHARESORNOT</td><td>NUMBER(5,0)</td><td></td><td>100.00%</td><td>0:非合并数据1:合并数据2:合并数据,但该基金代码属于不实际交易基金</td></tr><tr><td>7</td><td>份额变动原因</td><td>CHANGEREASON</td><td>VARCHAR2(10)</td><td>枚举类型</td><td>100.00%</td><td>导致基金份额变动的原因</td></tr><tr><td>8</td><td>基金合计份额(万份)</td><td>FUNDSHARE_TOTAL</td><td>NUMBER(20,6)</td><td></td><td>72.00%</td><td>分级基金的合计份额</td></tr><tr><td>9</td><td>最新标志</td><td>CUR_SIGN</td><td>NUMBER(5,0)</td><td></td><td>100.00%</td><td>记录基金的份额数据是否是最新份额</td></tr><tr><td>10</td><td>公告日期</td><td>ANN_DATE</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>披露基金份额的公告材料披露日期</td></tr><tr><td>11</td><td>非流通份额(万份)</td><td>F_INFO_NON_TRADABLE_S_HR</td><td>NUMBER(20,4)</td><td></td><td>2.00%</td><td>封闭式基金没有上市流通的份额</td></tr><tr><td>12</td><td>证券ID</td><td>SEC_ID</td><td>VARCHAR2(10)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的能够标识证券的老编码</td></tr><tr><td>13</td><td>基金场内代码</td><td>S_INFO_INNERODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>78.00%</td><td>基金在场内交易的交易代码</td></tr><tr><td>14</td><td>基金场外代码</td><td>S_INFO_OUTERODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>基金在场外交易的交易代码</td></tr><tr><td>15</td><td>截止日期</td><td>END_DT</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>记录当前该基金份额数据的日期</td></tr></table>