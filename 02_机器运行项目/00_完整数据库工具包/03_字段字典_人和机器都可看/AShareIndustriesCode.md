# 行业代码 - AShareIndustriesCode


简介


<table><tr><td>所属数据库:</td><td>基础代码表</td><td>历史长度:</td><td>15+年</td></tr><tr><td>所属模块:</td><td>基础代码表</td><td>数据披露频率:</td><td>日</td></tr><tr><td>国家地区:</td><td>中国</td><td>数据传输频率:</td><td>日内</td></tr><tr><td>数据范围:</td><td>覆盖Filesync产品中使用到的行业</td><td>数据传输时间:</td><td>07:30,18:00,22:30</td></tr><tr><td>文件格式:</td><td>Database、XML、TXT、CSV</td><td>全部记录数:</td><td>3.05万</td></tr><tr><td>产品说明:</td><td>记录板块列表,包括证监会行业分类、上交所行业分类、地域板块、概念板块、同系公司5套体系近千个板块</td><td>数据包大小:</td><td>11 MB/年</td></tr></table>

# 数据字典


业务主键： 最新板块代码 , 行业名称 , 是否有效


<table><tr><td>序号</td><td>字段中文名</td><td>字段名</td><td>字段类型</td><td>枚举/外部引用</td><td>有值率</td><td>释义</td></tr><tr><td>1</td><td>最新板块代码</td><td>NEW_INDUSTRIESCODE</td><td>VARCHAR2(38)</td><td></td><td>100.00%</td><td>万得自定义的对包含行业、地区、股票等一众分类在内的板块名称的原始代码</td></tr><tr><td>2</td><td>行业代码</td><td>INDUSTRIESCODE</td><td>VARCHAR2(38)</td><td></td><td>100.00%</td><td>万得自定义的对包含行业、地区、股票等一众分类在内的板块名称的原始代码</td></tr><tr><td>3</td><td>行业名称</td><td>INDUSTRIESNAME</td><td>VARCHAR2(100)</td><td></td><td>100.00%</td><td>万得自定义的包含行业、地区、股票等一众分类的板块名称；记录各类板块的中文名称；</td></tr><tr><td>4</td><td>级数</td><td>LEVELNUM</td><td>NUMBER(20,4)</td><td></td><td>100.00%</td><td>板块所属类别的级别编号</td></tr><tr><td>5</td><td>是否有效</td><td>USED</td><td>NUMBER(1,0)</td><td></td><td>100.00%</td><td>是否使用，1为正常使用，0为停止使用</td></tr><tr><td>6</td><td>板块别名</td><td>INDUSTRIESALIAS</td><td>VARCHAR2(30)</td><td></td><td>58.00%</td><td>所属业务板块的别名</td></tr><tr><td>7</td><td>展示序号</td><td>SEQUENCE</td><td>NUMBER(4,0)</td><td></td><td>3.00%</td><td>板块展示顺序编号</td></tr><tr><td>8</td><td>备注（废弃）</td><td>MEMO</td><td>VARCHAR2(100)</td><td></td><td>0.00%</td><td>62开头：记录Wind行业分类包含的行业内容61开头：申万原始行业代码76开头：申万2021版行业代码03开头：区号67开头：记录终止生效日</td></tr><tr><td>9</td><td>板块中文定义</td><td>CHINESEDEFINITION</td><td>VARCHAR2(2000)</td><td></td><td>13.00%</td><td>对板块含义的中文解释说明</td></tr><tr><td>10</td><td>板块英文名称</td><td>WIND_NAME_ENG</td><td>VARCHAR2(200)</td><td></td><td>40.00%</td><td>所属业务板块的英文名称</td></tr><tr><td>11</td><td>行业代码(旧)</td><td>INDUSTRIESCODE_OLD</td><td>VARCHAR2(38)</td><td></td><td>100.00%</td><td>万得自定义的对包含行业、地区、股票等一众分类在内的板块名称的原始代码</td></tr><tr><td>12</td><td>行政区域代码</td><td>REGION_CODE</td><td>VARCHAR2(600)</td><td></td><td>10.00%</td><td>在INDUSTRIESCODE为03地域板块会有值</td></tr></table>