import os
import csv
import json
import re
import time
from pathlib import Path
from datetime import datetime
import yaml
from blood_glucose_mcp import enrich_query_with_blood_glucose
from homepage_mcp import enrich_query_with_homepage_doctors
from medicheck_suggestions import enrich_query_with_medicheck_suggestions

CWD = os.path.abspath(os.path.dirname(__file__))

def create_schema_from_template(dic_template, use_preset_template,logger) -> dict:
        """
        将dic_template数组转换为JSON schema格式

        Args:
            dic_template (list): 格式为['42:性别', '45:民族', ...]的数组

        Returns:
            dict: JSON schema格式的字典
        """
        # 读取病历填充字典
        csv_path = os.path.join(CWD, "source","病历填充字典.csv")
        element_dict = {}
        
        try:
            with open(csv_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    element_id = row['ELEMENTID'].strip()
                    element_name = row['ELEMENTNAME'].strip()
                    ban = row['BAN'].strip()
                    description = row['DESCRIPTION'].strip()
                    
                    element_dict[element_id] = {
                        'name': element_name,
                        'ban': ban == 'TRUE',
                        'description': description if description else element_name
                    }
        except Exception as e:
            logger.warning(f"读取病历填充字典失败: {e}")
        
        properties = {}

        for item in dic_template:
            if ":" in item:
                _, field_name = item.split(":", 1)
                
                # 通过element_name查找对应的字典项
                found_element = None
                for element_id, element_info in element_dict.items():
                    if element_info['name'] == field_name:
                        found_element = element_info
                        break
                
                # 检查是否在字典中且BAN为TRUE，如果是则跳过
                if found_element and found_element['ban']:
                    continue
                
                # 使用字典中的描述，如果没有则使用原field_name
                description = field_name
                if found_element:
                    description = found_element['description']
                
                properties[field_name] = {"type": "string", "description": description}

        if use_preset_template:
            required = [item.split(":")[1] for item in dic_template]
        else:
            required = []
        schema = {"type": "object", "properties": properties, "required": required}

        return schema


def match_doc_type(doc_type, preset_doc_type, match_mode="contains") -> bool:
        """
        根据匹配模式判断当前文书类型是否命中预置模板。
        """
        if match_mode == "exact":
            return doc_type == preset_doc_type
        return preset_doc_type in doc_type


def _insert_required_field(required_fields, field_name, anchor_field, position):
        if field_name in required_fields:
            return required_fields

        if anchor_field in required_fields:
            anchor_index = required_fields.index(anchor_field)
            insert_index = anchor_index if position == "before" else anchor_index + 1
            required_fields.insert(insert_index, field_name)
            return required_fields

        required_fields.append(field_name)
        return required_fields


def apply_runtime_schema_fields(template_schema, runtime_schema_fields, logger):
        """
        按运行时规则向 schema 中注入临时字段。
        """
        if not runtime_schema_fields:
            return template_schema

        updated_schema = dict(template_schema)
        properties = dict(updated_schema.get("properties", {}))
        required = list(updated_schema.get("required", []))

        for field_rule in runtime_schema_fields:
            field_name = field_rule.get("FieldName", "").strip()
            description = field_rule.get("Description", "").strip() or field_name
            anchor_field = field_rule.get("AnchorField", "").strip()
            position = field_rule.get("Position", "before").strip().lower()
            is_required = field_rule.get("Required", True)

            if not field_name:
                logger.warning(f"运行时 schema 字段缺少 FieldName，跳过规则: {field_rule}")
                continue
            if field_name in properties:
                logger.warning(f"运行时 schema 字段 {field_name} 已存在，跳过注入")
                continue
            if position not in {"before", "after"}:
                logger.warning(f"运行时 schema 字段 {field_name} 的 Position={position} 非法，使用 before")
                position = "before"
            if not anchor_field or anchor_field not in properties:
                logger.warning(f"运行时 schema 字段 {field_name} 的锚点 {anchor_field} 不存在，跳过注入")
                continue

            runtime_field_schema = {"type": "string", "description": description}
            new_properties = {}
            for existing_field_name, existing_field_schema in properties.items():
                if position == "before" and existing_field_name == anchor_field:
                    new_properties[field_name] = runtime_field_schema
                new_properties[existing_field_name] = existing_field_schema
                if position == "after" and existing_field_name == anchor_field:
                    new_properties[field_name] = runtime_field_schema

            properties = new_properties

            if is_required:
                required = _insert_required_field(required, field_name, anchor_field, position)

            logger.info(f"已注入运行时 schema 字段: {field_name}, anchor={anchor_field}, position={position}")

        updated_schema["properties"] = properties
        updated_schema["required"] = required
        return updated_schema


def strip_transient_fields(answer, runtime_schema_fields, logger):
        """
        删除仅用于推理的临时字段，避免进入最终输出。
        """
        transient_field_names = [
            field_rule.get("FieldName", "").strip()
            for field_rule in runtime_schema_fields
            if field_rule.get("Transient", True) and field_rule.get("FieldName", "").strip()
        ]

        if not transient_field_names:
            return answer

        parsed_answer = answer
        if isinstance(answer, str):
            try:
                parsed_answer = json.loads(answer)
            except Exception:
                try:
                    import json_repair

                    parsed_answer = json_repair.loads(answer)
                except Exception as e:
                    logger.warning(f"解析 answer 失败，无法移除临时字段: {e}")
                    return answer

        if not isinstance(parsed_answer, dict):
            logger.warning(f"answer 不是对象类型，无法移除临时字段: {type(parsed_answer)}")
            return parsed_answer

        for field_name in transient_field_names:
            if field_name in parsed_answer:
                del parsed_answer[field_name]
                logger.info(f"已移除临时字段: {field_name}")

        return parsed_answer


def convert_answer_format(answer, dic_template_vk, doc_type):
        """
        将形如{"主诉":"xx", "现病史":"yy",...} 的answer转换为{"code":"xx", "code":"yy",...}的格式

        Args:
            answer (dict): 包含field_name:value的字典，格式为{"主诉":"xx", "现病史":"yy",...}
            dic_template_vk (dict): 格式为{'field_name':'code', 'field_name':'code', ...}的字典，用于建立field_name到code的映射

        Returns:
            dict: 转换后的字典，格式为{"42":"xx", "45":"yy",...}
        """
        if isinstance(answer, str):
            # print(answer)
            answer = json.loads(answer)
        
        if "门诊病历" in doc_type or "门(急)诊病历" in doc_type:
            # 交换收缩压和舒张压的值
            if '收缩压' in answer and '舒张压' in answer:
                answer['收缩压'], answer['舒张压'] = answer['舒张压'], answer['收缩压']


        # 转换格式
        converted_answer = []
        for field_name, value in answer.items():
            if field_name in dic_template_vk:
                code = dic_template_vk[field_name]
                value = str(value).replace("    \n","").replace("\n\n","\n").replace("\\n","\n").strip() # 格式整理，针对首次查房
                converted_answer.append({"key": code, "value": value})
        
        return json.dumps(converted_answer, ensure_ascii=False, indent=4)

def pre_process(mygpt, user_id, question, logger=None):
    try:
        import json_repair

        query_json = json_repair.loads(question)
    except ModuleNotFoundError:
        query_json = json.loads(question)
    try:
        user_name = query_json['OperInfo']['OperName']
    except Exception:
        user_name = ""

    save_path = os.path.join(
        CWD, "query_save", f"{user_name}_{user_id}_{time.strftime('%Y-%m-%d_%H-%M-%S')}.txt"
    )

    try:
        if 'TemperatureSheet' in query_json:
            query_json['最近体温体征表'] = {}
            query_json['最近体温体征表']['体温'] = query_json['TemperatureSheet'].get('T01', None)
            query_json['最近体温体征表']['脉率'] = query_json['TemperatureSheet'].get('P02', None)
            query_json['最近体温体征表']['呼吸'] = query_json['TemperatureSheet'].get('BRE', None)
            query_json['最近体温体征表']['血压'] = query_json['TemperatureSheet'].get('BP01', None)
            query_json['最近体温体征表']['心率'] = query_json['TemperatureSheet'].get('I03', None)
            query_json['最近体温体征表']['尿量'] = query_json['TemperatureSheet'].get('OUT_C', None)
            query_json['最近体温体征表']['入量'] = query_json['TemperatureSheet'].get('IN_C', None)
            query_json['最近体温体征表']['体重'] = query_json['TemperatureSheet'].get('W01', None)
            query_json['最近体温体征表']['身高'] = query_json['TemperatureSheet'].get('H01', None)
            del query_json['TemperatureSheet']
    except:
        pass

    query_json = enrich_query_with_blood_glucose(query_json, logger)
    query_json = enrich_query_with_homepage_doctors(query_json, logger)
    query_json = enrich_query_with_medicheck_suggestions(query_json, logger)

    # 重新排列键序：文档基本信息排在前面，DocInfos等排在后面
    _priority_keys = ["DocType", "CommandInfo", "OperInfo", "PatInfo"]
    _ordered = {k: query_json[k] for k in _priority_keys if k in query_json}
    _ordered.update({k: v for k, v in query_json.items() if k not in _priority_keys})
    Path(save_path).write_text(json.dumps(_ordered, ensure_ascii=False, indent=4))

    return query_json, save_path

def clear_doc_info(text: str) -> str:
    """
    清理隐私信息，如姓名、住址、身份证号、手机号、邮箱等
    将文本中连续的\r\n处理为单个\n
    Args:
        text (str): 输入的文本字符串

    Returns:
        str: 处理后的文本字符串
    """
    
    # 首先将所有的\r\n替换为\n
    text = text.replace("\r\n", "\n")

    # 清理隐私信息模式1: "字段名\n具体信息" 格式 - 完全删除
    privacy_patterns = [
        r'姓名\n[^\n]+',
        r'工作单位\n[^\n]+', 
        r'现住址\n[^\n]+',
        r'身份证\n[^\n]+',
        r'住院号\n[^\n]+',
        r'医疗保障凭证号/身份证号\n[^\n]+',
        r'医疗机构编码\n[^\n]+'
    ]
    
    for pattern in privacy_patterns:
        text = re.sub(pattern, '', text)
    
    # 清理隐私信息模式2: "字段名：具体信息" 格式 - 完全删除
    colon_patterns = [
        r'姓名[：:][^\n]+',
        r'工作单位[：:][^\n]+',
        r'现住址[：:][^\n]+',
        r'身份证[：:][^\n]+',
        r'住院号[：:][^\n]+',
        r'医疗机构编码[：:][^\n]+',
        r'手机号[：:][^\n]+'
    ]
    
    for pattern in colon_patterns:
        text = re.sub(pattern, '', text)
    
    # 清理隐私信息模式3: 身份证号码（15位或18位数字）
    text = re.sub(r'\b\d{15}\b|\b\d{17}[\dXx]\b', '', text)
    
    # 清理隐私信息模式4: 住院号（10位数字）
    text = re.sub(r'\b\d{10}\b', '', text)
    
    # 清理隐私信息模式5: 手机号（11位数字）
    text = re.sub(r'\b1[3-9]\d{9}\b', '', text)
    
    # 清理隐私信息模式6: 邮箱地址
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', text)
    
    # 清理隐私信息模式7: 详细地址（包含省市区街道门牌号等）
    text = re.sub(r'[^\n]*?[省市区县][^\n]*?[路街道巷弄][^\n]*?[号栋单元室]?[^\n]*', '', text)
    
    # 清理隐私信息模式8: 医疗机构编码（H开头的编码）
    text = re.sub(r'\bH\d{11}\b', '', text)
    
    # 提取姓名用于后续替换（从"患者XXX"模式中提取）
    name_matches = re.findall(r'患者([\u4e00-\u9fa5]{2,4})，?', text)
    
    # 清理隐私信息模式7: "患者XXX" 格式中的姓名
    for name in set(name_matches):  # 使用set去重
        if len(name) >= 2:  # 确保是合理的姓名长度
            # 替换"患者姓名"为"患者"
            text = re.sub(f'患者{re.escape(name)}，?', '患者，', text)
            # 替换其他地方出现的姓名
            text = re.sub(f'\b{re.escape(name)}\b', '[患者姓名]', text)
    
    # 处理连续的\n
    while "\n\n" in text:
        text = text.replace("\n\n", "\n")

    # 如果有连续超过三个以上的空格，替换为两个空格
    text = re.sub(r' {3,}', '  ', text)
    
    # 清理空行和多余的空白
    text = re.sub(r'\n\s*\n', '\n', text)
    text = text.strip()

    return text



def choose_preset_dic_template(query_json, logger):
    """
    根据doc_type选择预设的dic_template，如果不存在，从query_json中获取DicTemplate
    """
    doc_type = query_json.get("DocType", "")
    template_advise = ""

    # 从query_json中获取DicTemplate
    dic_template = query_json.get("DicTemplate", "")
    if not dic_template:
        logger.warning("query_json 中缺少 DicTemplate，返回空模板")
        return [], "", {}, False, 15, []
    dic_template = dic_template.split("\r\n")
    dic_template_values = [item.split(":")[1] for item in dic_template]
    # dic_template 样例['2046807:结婚年龄', '2046808:健康状况'...]
    dic_template_vk = {}
    for item in dic_template:
        dic_template_vk[item.split(":")[1]] = item.split(":")[0]

    # 查找有没有预设置模版
    # preset_dic_template = json.load(open(os.path.join(CWD, "source", "preset_dic_template.json"), "r", encoding="utf-8"))
    # yaml版本
    with open(os.path.join(CWD, "source", "preset_dic_template.yaml"), "r", encoding="utf-8") as f:
        preset_dic_template = yaml.safe_load(f)

    use_preset_template = False
    template_advise = ""
    day_limit = 15
    runtime_schema_fields = []
    for item in preset_dic_template:
        match_mode = item.get("DocTypeMatch", "contains")
        if match_doc_type(doc_type, item["DocType"], match_mode):
            logger.info(f"{doc_type} 匹配到预置模板: {item['DicTemplate']}")
            choose_element = []
            use_preset_template = True
            day_limit = item.get("DayLimit", 15)
            runtime_schema_fields = item.get("RuntimeSchemaFields", []) or []
            # 如果是空的dictemplate，保留原来的
            if len(item["DicTemplate"]) > 0:
                # 如果预置模板中的元素在query_json的DicTemplate中，就添加到choose_element中
                for element in item["DicTemplate"]:
                    if element in dic_template_values:
                        # 获取对应的id
                        choose_element.append(f"{dic_template_vk[element]}:{element}")
                    else:
                        logger.error(f"匹配到预置模板: {item['DicTemplate']}。但元素 {element} 不在 {doc_type} 的 DicTemplate 中")
                dic_template = choose_element
            # 如果 item有exclude数组，就从choose_element中删除
            elif "Exclude" in item:
                logger.info(f"排除元素: {item['Exclude']}")
                for element in dic_template_values:
                    if not element in item["Exclude"]:
                        choose_element.append(f"{dic_template_vk[element]}:{element}")
                dic_template = choose_element
                    
            
            template_advise = item.get("TemplateAdvise", "")
            break
    
    return dic_template, template_advise, dic_template_vk, use_preset_template, day_limit, runtime_schema_fields

def clear_context(query_json, logger):
    """
    清理query_json中DocInfos数组中不必要的DocType
    """
    doc_infos = query_json.get("DocInfos", [])
    current_doc_type = query_json.get("DocType", "")
    # clear_doctype_list = ["同意书","评分表"]
    clear_doctype_list = ["评分表"] # 删除
    crop_doctype_list = ["同意书"] # 同意书内容减半

    
    # 过滤掉包含不必要DocType的项
    filtered_doc_infos = [
        item for item in doc_infos 
        if not any(clear_doctype in item.get("DocType", "") for clear_doctype in clear_doctype_list)
    ]
    
    # 对同意书类型的文档内容减半处理
    for item in filtered_doc_infos:
        if any(crop_doctype in item.get("DocType", "") for crop_doctype in crop_doctype_list):
            content = item.get("Content", "")
            if content:
                # 取前一半内容
                half_length = len(content) // 2
                item["Content"] = content[:half_length] + "..."
    
    # 将DocType="正式病历"改为"既往门诊病历"
    for item in filtered_doc_infos:
        if item.get("DocType", "") == "正式病历":
            item["DocType"] = "既往门诊病历"

    if "入院记录" in current_doc_type and (len(query_json.get("CommandInfo", "").strip()) > 50):
        filtered_doc_infos = [item for item in filtered_doc_infos if "入院记录" not in item.get("DocType", "")]
        logger.info(f"过滤掉入院记录: {filtered_doc_infos}")

    # if "首次病程记录" in current_doc_type:
    #     filtered_doc_infos = [item for item in filtered_doc_infos if "首程" not in item.get("DocType", "")]
    
    query_json["DocInfos"] = filtered_doc_infos
    return query_json, current_doc_type


def sort_cut_context(data, retain_days=30):
    """
    按时间排序各种医疗信息对象
    
    Args:
        data (dict): 已解析的医疗数据字典
    
    Returns:
        dict: 处理后的字典，各对象按时间从远到近排序
    """
    from datetime import datetime
    
    # 辅助函数：解析时间字符串
    def parse_datetime(date_str):
        if not date_str:
            return datetime.min
        try:
            # 尝试多种时间格式
            formats = [
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d %H:%M',
                '%Y-%m-%d',
                '%Y/%m/%d %H:%M:%S',
                '%Y/%m/%d %H:%M',
                '%Y/%m/%d'
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
            return datetime.min
        except:
            return datetime.min
    
    # 处理DocInfos
    if 'DocInfos' in data and isinstance(data['DocInfos'], list) and data['DocInfos']:
        try:
            data['DocInfos'] = sorted(
                data['DocInfos'],
                key=lambda x: parse_datetime(x.get('CreateDate', ''))
            )
            # 删除CreateDate键
            # for item in data['DocInfos']:
            #     if isinstance(item, dict) and 'CreateDate' in item:
            #         del item['CreateDate']
        except Exception:
            # 如果排序失败，保持原始顺序，只删除CreateDate键
            for item in data['DocInfos']:
                if isinstance(item, dict) and 'CreateDate' in item:
                    del item['CreateDate']
    
    # 处理ExamInfos
    if 'ExamInfos' in data and isinstance(data['ExamInfos'], list) and data['ExamInfos']:
        try:
            data['ExamInfos'] = sorted(
                data['ExamInfos'],
                key=lambda x: parse_datetime(x.get('CreateDate', ''))
            )
            # 删除CreateDate键和ItemName
            for item in data['ExamInfos']:
                # if isinstance(item, dict) and 'CreateDate' in item:
                #     del item['CreateDate']
                if isinstance(item, dict) and 'ItemName' in item:
                    del item['ItemName']
        except Exception:
            # 如果排序失败，保持原始顺序，只删除CreateDate键
            for item in data['ExamInfos']:
                if isinstance(item, dict) and 'CreateDate' in item:
                    del item['CreateDate']
    
    # 处理LisInfos
    if 'LisInfos' in data and isinstance(data['LisInfos'], list) and data['LisInfos']:
        try:
            data['LisInfos'] = sorted(
                data['LisInfos'],
                key=lambda x: parse_datetime(x.get('CreateDate', ''))
            )
            # 删除CreateDate、Id键、ItemName
            for item in data['LisInfos']:
                if isinstance(item, dict):
                    # if 'CreateDate' in item:
                    #     del item['CreateDate']
                    if 'Id' in item:
                        del item['Id']
                    if 'ItemName' in item:
                        del item['ItemName']
        except Exception:
            # 如果排序失败，保持原始顺序，只删除CreateDate和Id键
            for item in data['LisInfos']:
                if isinstance(item, dict):
                    if 'CreateDate' in item:
                        del item['CreateDate']
                    if 'Id' in item:
                        del item['Id']
    
    # 处理OrderInfo中的OrderLong和OrderShort
    if 'OrderInfo' in data and isinstance(data['OrderInfo'], dict) and data['OrderInfo']:
        order_info = data['OrderInfo']
        
        # 处理OrderLong
        if 'OrderLong' in order_info and isinstance(order_info['OrderLong'], list) and order_info['OrderLong']:
            try:
                # 每个元素应该是字符串，格式为 "数字 日期时间 内容"
                sorted_long = []
                for item in order_info['OrderLong']:
                    if isinstance(item, str):
                        # 使用正则表达式提取日期时间部分
                        # 格式: "数字 YYYY-MM-DD HH:MM:SS 内容"
                        import re
                        match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', item)
                        if match:
                            time_part = match.group(1)
                            parsed_time = parse_datetime(time_part)
                            if parsed_time != datetime.min:
                                sorted_long.append((parsed_time, item))
                            else:
                                # 时间解析失败，保持原始医嘱
                                sorted_long.append((datetime.min, item))
                        else:
                            # 如果没有匹配到标准格式，尝试其他格式
                            match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})', item)
                            if match:
                                time_part = match.group(1)
                                parsed_time = parse_datetime(time_part)
                                if parsed_time != datetime.min:
                                    sorted_long.append((parsed_time, item))
                                else:
                                    # 时间解析失败，保持原始医嘱
                                    sorted_long.append((datetime.min, item))
                            else:
                                # 无法提取时间，保持原始医嘱
                                sorted_long.append((datetime.min, item))
                    else:
                        sorted_long.append((datetime.min, item))
                
                # 按时间排序
                sorted_long.sort(key=lambda x: x[0])
                # 删除序号并保存
                cleaned_long = []
                for item in sorted_long:
                    try:
                        # 使用正则表达式删除开头的序号
                        cleaned_item = re.sub(r'^\d+\.\s*', '', item[1])
                        cleaned_long.append(cleaned_item)
                    except Exception:
                        # 序号删除失败，保持原始医嘱
                        cleaned_long.append(item[1])
                order_info['长期医嘱'] = cleaned_long
                del order_info['OrderLong']
            except Exception:
                # 整个处理过程失败，保持原始数据但重命名
                order_info['长期医嘱'] = order_info['OrderLong']
                del order_info['OrderLong']
        
        # 处理OrderShort
        if 'OrderShort' in order_info and isinstance(order_info['OrderShort'], list) and order_info['OrderShort']:
            try:
                # 每个元素应该是字符串，格式为 "数字 日期时间 内容"
                sorted_short = []
                for item in order_info['OrderShort']:
                    if isinstance(item, str):
                        # 使用正则表达式提取日期时间部分
                        # 格式: "数字 YYYY-MM-DD HH:MM:SS 内容"
                        import re
                        match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', item)
                        if match:
                            time_part = match.group(1)
                            parsed_time = parse_datetime(time_part)
                            if parsed_time != datetime.min:
                                sorted_short.append((parsed_time, item))
                            else:
                                # 时间解析失败，保持原始医嘱
                                sorted_short.append((datetime.min, item))
                        else:
                            # 如果没有匹配到标准格式，尝试其他格式
                            match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})', item)
                            if match:
                                time_part = match.group(1)
                                parsed_time = parse_datetime(time_part)
                                if parsed_time != datetime.min:
                                    sorted_short.append((parsed_time, item))
                                else:
                                    # 时间解析失败，保持原始医嘱
                                    sorted_short.append((datetime.min, item))
                            else:
                                # 无法提取时间，保持原始医嘱
                                sorted_short.append((datetime.min, item))
                    else:
                        sorted_short.append((datetime.min, item))
                
                # 按时间排序
                sorted_short.sort(key=lambda x: x[0])
                # 删除序号并保存
                cleaned_short = []
                for item in sorted_short:
                    try:
                        # 使用正则表达式删除开头的序号
                        cleaned_item = re.sub(r'^\d+\.\s*', '', item[1])
                        cleaned_short.append(cleaned_item)
                    except Exception:
                        # 序号删除失败，保持原始医嘱
                        cleaned_short.append(item[1])
                order_info['临时医嘱'] = cleaned_short
                del order_info['OrderShort']
            except Exception:
                # 整个处理过程失败，保持原始数据但重命名
                order_info['临时医嘱'] = order_info['OrderShort']
                del order_info['OrderShort']
    
    # 根据保留时间过滤内容
    if retain_days > 0:
        from datetime import datetime, timedelta
        
        # 找到所有文档中的最晚时间
        latest_time = datetime.min
        
        # 从DocInfos中查找最晚时间
        if 'DocInfos' in data and isinstance(data['DocInfos'], list) and data['DocInfos']:
            for item in data['DocInfos']:
                if isinstance(item, dict) and 'Content' in item:
                    content = str(item['Content'])
                    import re
                    time_match = re.search(r'(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)', content)
                    if time_match:
                        item_time = parse_datetime(time_match.group(1))
                        if item_time > latest_time:
                            latest_time = item_time
        
        # 从ExamInfos中查找最晚时间
        if 'ExamInfos' in data and isinstance(data['ExamInfos'], list) and data['ExamInfos']:
            for item in data['ExamInfos']:
                if isinstance(item, dict) and 'Content' in item:
                    content = str(item['Content'])
                    import re
                    time_match = re.search(r'(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)', content)
                    if time_match:
                        item_time = parse_datetime(time_match.group(1))
                        if item_time > latest_time:
                            latest_time = item_time
        
        # 从LisInfos中查找最晚时间
        if 'LisInfos' in data and isinstance(data['LisInfos'], list) and data['LisInfos']:
            for item in data['LisInfos']:
                if isinstance(item, dict) and 'Content' in item:
                    content = str(item['Content'])
                    import re
                    time_match = re.search(r'(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)', content)
                    if time_match:
                        item_time = parse_datetime(time_match.group(1))
                        if item_time > latest_time:
                            latest_time = item_time
        
        # 从OrderInfo中查找最晚时间
        if 'OrderInfo' in data and isinstance(data['OrderInfo'], dict) and data['OrderInfo']:
            order_info = data['OrderInfo']
            # 检查长期医嘱
            if '长期医嘱' in order_info and isinstance(order_info['长期医嘱'], list):
                for item in order_info['长期医嘱']:
                    if isinstance(item, str):
                        import re
                        time_match = re.search(r'(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)', item)
                        if time_match:
                            item_time = parse_datetime(time_match.group(1))
                            if item_time > latest_time:
                                latest_time = item_time
            # 检查临时医嘱
            if '临时医嘱' in order_info and isinstance(order_info['临时医嘱'], list):
                for item in order_info['临时医嘱']:
                    if isinstance(item, str):
                        import re
                        time_match = re.search(r'(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)', item)
                        if time_match:
                            item_time = parse_datetime(time_match.group(1))
                            if item_time > latest_time:
                                latest_time = item_time
        
        # 如果没有找到任何时间，使用当前时间
        if latest_time == datetime.min:
            latest_time = datetime.now()
        
        # 以最晚时间为基准倒推retain_days天
        cutoff_date = latest_time - timedelta(days=retain_days)

        MAX_CONTEXT = 65535
        # 根据内容长度动态调整保留天数，确保不超过最大上下文
        try:
            import tiktoken
            def _count_tokens(text: str) -> int:
                try:
                    enc = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    enc = tiktoken.get_encoding("cl100k_base")
                return len(enc.encode(text))
        except Exception:
            tiktoken = None
            def _count_tokens(text: str) -> int:
                # 回退：如果没有tiktoken，使用字符数近似作为令牌数
                return len(text)
        import json
        import copy
        import re

        time_pattern = r'(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)'

        def _extract_time(text):
            if text is None:
                return None
            time_match = re.search(time_pattern, str(text))
            if not time_match:
                return None
            parsed = parse_datetime(time_match.group(1))
            if parsed == datetime.min:
                return None
            return parsed

        def _filter_docs(items, cutoff):
            filtered_docs = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                doc_type = item.get('DocType', '')
                if '首程' in str(doc_type) or '上级医师首次查房' in str(doc_type):
                    filtered_docs.append(item)
                    continue
                item_time = _extract_time(item.get('Content', ''))
                if item_time is None or item_time >= cutoff:
                    filtered_docs.append(item)
            return filtered_docs

        def _filter_content_list(items, cutoff):
            filtered_items = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_time = _extract_time(item.get('Content', ''))
                if item_time is None or item_time >= cutoff:
                    filtered_items.append(item)
            return filtered_items

        def _filter_order_list(items, cutoff):
            filtered_items = []
            for item in items:
                if not isinstance(item, str):
                    filtered_items.append(item)
                    continue
                item_time = _extract_time(item)
                if item_time is None or item_time >= cutoff:
                    filtered_items.append(item)
            return filtered_items

        def _token_count_payload(payload):
            try:
                text = json.dumps(payload, ensure_ascii=False)
            except Exception:
                text = str(payload)
            return _count_tokens(text)

        def _split_items_by_time(items, content_getter):
            no_time = []
            timed = []
            for item in items:
                item_time = _extract_time(content_getter(item))
                if item_time is None:
                    no_time.append(item)
                else:
                    timed.append((item_time, item))
            timed.sort(key=lambda x: x[0], reverse=True)
            return no_time, [item for _, item in timed]

        def _trim_list_to_target(items, content_getter, apply_list, target_tokens):
            if not isinstance(items, list) or not items:
                return
            no_time_items, timed_items = _split_items_by_time(items, content_getter)
            if not timed_items:
                return
            low, high = 0, len(timed_items)
            best = 0
            while low <= high:
                mid = (low + high) // 2
                apply_list(no_time_items + timed_items[:mid])
                current_tokens = _token_count_payload(data)
                if current_tokens <= target_tokens:
                    best = mid
                    low = mid + 1
                else:
                    high = mid - 1
            apply_list(no_time_items + timed_items[:best])

        adjusted_days = max(3, int(retain_days))
        while True:
            temp_cutoff = latest_time - timedelta(days=adjusted_days)
            tmp = copy.deepcopy(data)
            if 'DocInfos' in tmp and isinstance(tmp['DocInfos'], list) and tmp['DocInfos']:
                tmp['DocInfos'] = _filter_docs(tmp['DocInfos'], temp_cutoff)
            tokens = _token_count_payload(tmp)
            if tokens <= MAX_CONTEXT or adjusted_days <= 3:
                break
            new_days = max(3, adjusted_days // 2)
            if new_days == adjusted_days:
                break
            adjusted_days = new_days

        # 使用最终调整后的天数更新截止日期
        retain_days = adjusted_days
        cutoff_date = latest_time - timedelta(days=retain_days)
        # 过滤DocInfos - 基于处理时已删除的CreateDate，需要重新解析时间
        if 'DocInfos' in data and isinstance(data['DocInfos'], list) and data['DocInfos']:
            data['DocInfos'] = _filter_docs(data['DocInfos'], cutoff_date)

        final_tokens = _token_count_payload(data)
        if final_tokens > MAX_CONTEXT:
            target_tokens = int(MAX_CONTEXT * 0.95)
            if 'OrderInfo' in data and isinstance(data['OrderInfo'], dict) and data['OrderInfo']:
                order_info = data['OrderInfo']
                if _token_count_payload(data) > target_tokens and '长期医嘱' in order_info and isinstance(order_info['长期医嘱'], list):
                    _trim_list_to_target(
                        order_info['长期医嘱'],
                        lambda x: x if isinstance(x, str) else "",
                        lambda new_items: order_info.__setitem__('长期医嘱', new_items),
                        target_tokens
                    )
                if _token_count_payload(data) > target_tokens and '临时医嘱' in order_info and isinstance(order_info['临时医嘱'], list):
                    _trim_list_to_target(
                        order_info['临时医嘱'],
                        lambda x: x if isinstance(x, str) else "",
                        lambda new_items: order_info.__setitem__('临时医嘱', new_items),
                        target_tokens
                    )
                if _token_count_payload(data) > target_tokens and 'OrderLong' in order_info and isinstance(order_info['OrderLong'], list):
                    _trim_list_to_target(
                        order_info['OrderLong'],
                        lambda x: x if isinstance(x, str) else "",
                        lambda new_items: order_info.__setitem__('OrderLong', new_items),
                        target_tokens
                    )
                if _token_count_payload(data) > target_tokens and 'OrderShort' in order_info and isinstance(order_info['OrderShort'], list):
                    _trim_list_to_target(
                        order_info['OrderShort'],
                        lambda x: x if isinstance(x, str) else "",
                        lambda new_items: order_info.__setitem__('OrderShort', new_items),
                        target_tokens
                    )
            if _token_count_payload(data) > target_tokens and 'LisInfos' in data and isinstance(data['LisInfos'], list) and data['LisInfos']:
                _trim_list_to_target(
                    data['LisInfos'],
                    lambda x: x.get('Content', '') if isinstance(x, dict) else "",
                    lambda new_items: data.__setitem__('LisInfos', new_items),
                    target_tokens
                )
            if _token_count_payload(data) > target_tokens and 'ExamInfos' in data and isinstance(data['ExamInfos'], list) and data['ExamInfos']:
                _trim_list_to_target(
                    data['ExamInfos'],
                    lambda x: x.get('Content', '') if isinstance(x, dict) else "",
                    lambda new_items: data.__setitem__('ExamInfos', new_items),
                    target_tokens
                )
    
    return data



def process_consult_doc(query_json, dept):
    # 识别会诊科室并提取会诊请求

    def _parse_dt(date_str: str):
        if not date_str:
            return datetime.min
        for fmt in (
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d',
            '%Y/%m/%d %H:%M:%S',
            '%Y/%m/%d %H:%M',
            '%Y/%m/%d',
        ):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return datetime.min

    latest_dt = None
    latest_request = ""
    latest_date_str = ""
    
    try:
        for doc in query_json.get('DocInfos', []):
            if '会诊记录单' in doc.get('DocType', ''):
                content = doc.get('Content', '') or ''
                if f"邀请会诊医疗机构、科别：{dept}" in content:
                    date_str = doc.get('CreateDate', '') or ''
                    dt = _parse_dt(date_str)
                    if latest_dt is None or dt >= latest_dt:
                        latest_dt = dt
                        latest_date_str = date_str
                        # 提取「申请会诊的原因及目的」到「申请会诊的科别」之间的文本
                        try:
                            part = content.split("申请会诊的原因及目的：", 1)[1]
                            latest_request = part.split("申请会诊的科别：", 1)[0].strip()
                        except Exception:
                            latest_request = ""
                else:
                    # print(f"【content】: {content}")
                    pass
        # 如果两个dept一致，说明是在请求会诊而不是接收会诊                    
        doc_dept = query_json['PatInfo'].get('DeptName') 
        oper_dept = query_json['OperInfo'].get('LoginDeptName')
        if doc_dept == oper_dept:
            latest_request = ""
    except Exception:
        latest_request = ""

    return latest_request, latest_date_str



if __name__ == "__main__":
    # 测试sort_cut_context函数
    # 创建测试数据
    test_data = json.load(open("test/samples/createDate.txt", "r", encoding="utf-8"))

    out_data = sort_cut_context(test_data, retain_days=30)

    with open("test/samples/createDate_sorted.txt", "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
