# 术语库数据结构说明

## 1. 文件位置

当前术语库文件位于：

```text
termbase/auto_regulation_terms.csv
样例术语库文件位于：

复制
termbase/auto_regulation_terms_sample.csv
2. 术语库目标
本术语库用于汽车标准法规翻译场景，主要支撑以下能力：

翻译前识别源文中的汽车法规专业术语；
翻译时将命中术语注入 Prompt；
翻译后检查译文是否使用指定中文译法；
支撑术语一致率统计；
为后续术语强约束、术语后处理和质量评估提供基础数据。
3. 字段定义
字段名	是否必填	说明	示例
term_id	是	术语唯一 ID	en_0001
source_lang	是	源语言代码	en
source_term	是	源语言术语	type approval
target_lang	是	目标语言代码，当前默认为中文	zh
target_term	是	指定中文译法	型式认证
domain	是	所属领域	certification
priority	是	术语优先级	high
case_sensitive	是	是否大小写敏感	false
match_type	是	匹配方式	exact
note	否	备注说明	认证法规术语
4. 字段取值规范
4.1 source_lang
当前优先支持 RFP 重点语种：

语言代码	语言
en	英语
es	西班牙语
ru	俄语
de	德语
fr	法语
th	泰语
ar	阿拉伯语
当前首批术语优先覆盖：

复制
en, ru, de, fr, ar
4.2 target_lang
当前统一为：

复制
zh
表示翻译目标语言为中文。

4.3 domain
domain 用于标识术语所属业务领域。

建议取值包括：

domain	说明
general	通用汽车法规术语
certification	认证与型式批准
braking	制动系统
lighting	灯光与信号装置
emission	排放
hvac	暖通、除霜、空调
test	试验与检测
document	法规文档结构
modal	法规情态词
compliance	合规与一致性
4.4 priority
priority 表示术语约束优先级。

priority	说明
high	高优先级，翻译中应强制使用指定译法
medium	中优先级，建议使用指定译法
low	低优先级，可根据上下文调整
4.5 case_sensitive
case_sensitive 表示术语匹配时是否大小写敏感。

值	说明
true	大小写敏感
false	大小写不敏感
当前建议默认使用：

复制
false
4.6 match_type
match_type 表示术语匹配方式。

match_type	说明
exact	精确匹配
fuzzy	模糊匹配，后续扩展
regex	正则匹配，后续扩展
当前 V0.1 阶段主要使用：

复制
exact
5. 当前 V0.1 术语库范围
当前首批术语库覆盖以下类型：

汽车法规通用术语；
型式认证相关术语；
制动系统术语；
灯光与信号装置术语；
排放法规术语；
试验检测术语；
法规文档结构术语；
法规情态词；
俄语、德语、法语、阿拉伯语少量核心术语。
6. 后续使用方式
术语库后续将被以下模块使用：

load_terms.py：读取术语库；
match_terms.py：在源文中匹配术语；
check_term_consistency.py：检查译文术语一致性；
翻译 Prompt 注入模块：将命中术语传入翻译模型；
术语错误导出模块：导出未使用指定译法的样本。
7. 术语一致率计算公式
术语一致率定义为：

术语一致率
=
译文中使用指定译法的术语出现次数
源文中命中术语库的术语总次数
×
100
%
术语一致率= 
源文中命中术语库的术语总次数
译文中使用指定译法的术语出现次数
​
 ×100%
本项目 RFP 要求术语一致率达到：

95
%
95%
复制

---

## 7. 验证文件是否已经在服务器上

如果你是在 VS Code 本地创建并通过 SFTP 同步到服务器，保存后在服务器终端执行：

```bash
cd /home/SERVICE_USER/llm-translation-poc

ls termbase
ls docs
预期看到：

复制
auto_regulation_terms.csv
auto_regulation_terms_sample.csv
以及：

复制
termbase_schema.md
进一步查看前几行：

复制
head -n 5 termbase/auto_regulation_terms.csv
head -n 20 docs/termbase_schema.md