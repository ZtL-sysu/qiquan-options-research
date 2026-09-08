# 中国共同基金业绩比较基准配置 - ChinaMutualFundBenchMark


简介


<table><tr><td>所属数据库:</td><td>中国共同基金数据库</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>共同基金-基础信息</td><td>数据披露频率:</td><td>日</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>日内</td></tr><tr><td>数据范围:</td><td>覆盖上海、深圳、场外公募基金</td><td>数据传输时间:</td><td>00:00,08:30,09:00,15:30,16:30,20:00</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>全部记录数:</td><td>6.95万</td></tr><tr><td>产品说明:</td><td>记录基金业绩比较基准的相关配置信息</td><td>数据包大小:</td><td>16 MB/年</td></tr></table>

# 数据字典


业务主键： 起始日期 , 截止日期 , 证券ID , 证券ID2


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>Wind代码</td><td>S_INFO_WINDCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>100.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>2</td><td>指数Wind代码</td><td>S_INFO_INDEXWINDCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>98.00%</td><td>万得自定义的用来识别证券的唯一编码,后缀为交易场所</td></tr><tr><td>3</td><td>起始日期</td><td>S_INFO_BGNDT</td><td>VARCHAR2(8)</td><td></td><td>99.00%</td><td>基金参照业绩比较基准运行的开始时间</td></tr><tr><td>4</td><td>截止日期</td><td>S_INFO_ENDDT</td><td>VARCHAR2(8)</td><td></td><td>17.00%</td><td>基金参照业绩比较基准运行的终止时间</td></tr><tr><td>5</td><td>指数权重</td><td>S_INFO_INDEXWEG</td><td>NUMBER(20,4)</td><td></td><td>100.00%</td><td>基金进行业绩参照时当前指数所占的百分比</td></tr><tr><td>6</td><td>运算符</td><td>S_INFO_OPERATORS</td><td>VARCHAR2(20)</td><td></td><td>1.00%</td><td>当前指数占比运算使用成算或者加算所使用的运算方式</td></tr><tr><td>7</td><td>常数</td><td>S_INFO_CONSTANT</td><td>NUMBER(20,4)</td><td></td><td>1.00%</td><td>运算指标时所使用的常量</td></tr><tr><td>8</td><td>是否税后</td><td>S_INFO_AFTERTAXORNOT</td><td>NUMBER(1,0)</td><td></td><td>100.00%</td><td>指标计算时是否计算税费</td></tr><tr><td>9</td><td>是否最新</td><td>CUR_SIGN</td><td>NUMBER(1,0)</td><td></td><td>100.00%</td><td>是否是当前业绩比较基准参照的最新指数</td></tr><tr><td>10</td><td>公告日期</td><td>ANN_DT</td><td>VARCHAR2(8)</td><td></td><td>100.00%</td><td>基金公司披露证券指数业绩比较基准公告的日期</td></tr><tr><td>11</td><td>汇率Wind代码</td><td>S_INFO_FXCODE</td><td>VARCHAR2(40)</td><td>WindCustome</td><td>5.00%</td><td>交易所公布的证券代码,特殊情况下可能是万得自编代码;交易所公布代码(特殊情款(无公布代码或公布代码需修改)为万得自编代码);交易所公布的用来标识某个证券的编码;基金产品在市场中对应的唯一标识代码;万得自定义的用来识别证券的唯一编码(去除后缀);交易所公布代码,若未公布为万得自编代码;</td></tr><tr><td>12</td><td>序号</td><td>S_INC_SEQUENCE</td><td>NUMBER(2,0)</td><td></td><td>100.00%</td><td>存在多个业绩比较基准时对业绩比较基准进行排序的编号</td></tr><tr><td>13</td><td>证券ID</td><td>SEC_ID</td><td>VARCHAR2(10)</td><td>WindCustome</td><td>100.00%</td><td>证券指数在万得数据库中对应的唯一标识</td></tr><tr><td>14</td><td>证券ID2</td><td>SEC_ID2</td><td>VARCHAR2(10)</td><td>WindCustome</td><td>98.00%</td><td>业绩比较基准对应指数在万得数据库中对应的唯一标识</td></tr><tr><td>15</td><td>是否复利</td><td>IS_COMPOUND</td><td>NUMBER(1,0)</td><td></td><td>100.00%</td><td>行情数据进行利润计算时是否按照复利进行计算</td></tr></table>