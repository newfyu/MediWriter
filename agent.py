import os
from loguru import logger
import time
import sys
import json

# Agent主目录
CWD = os.path.abspath(os.path.dirname(__file__))
sys.path.append(CWD)

from mediwriter_utils import (
    apply_runtime_schema_fields,
    create_schema_from_template,
    convert_answer_format,
    pre_process,
    clear_doc_info,
    choose_preset_dic_template,
    clear_context,
    sort_cut_context,
    process_consult_doc,
    strip_transient_fields,
)

class Agent: 
    def __init__(self):
        self.name = "MediWriter"
        self.description = "你是一个医疗文书写作的助手，主要完成各种病历的书写"
        self.model_config = [
            os.path.join(CWD, "model_hub/jlp-llm.yaml"),
            os.path.join(CWD, "model_hub/qwen3-next.yaml"),
            # os.path.join(CWD, "model_hub/r1-34b-awq.yaml"),
            os.path.join(CWD, "model_hub/qwen-flash.yaml"),
        ]
        self.model_config2 = [
            os.path.join(CWD, "model_hub/jlp-llm.yaml"),
            os.path.join(CWD, "model_hub/qwen3-next.yaml"),
            os.path.join(CWD, "model_hub/qwen-flash.yaml"),
        ]


    def run(self, question, context, mygpt, model_config_yaml, **kwargs):
        """ """

        user_id = kwargs.get("chat_id", "")
        # 配置日志：warning和error级别写入文件，info级别不写入文件
        log_file_path = os.path.join(CWD, "logs", f"mediwriter_{user_id}.log")
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        # 移除所有现有的处理器
        logger.remove()
        # 添加控制台处理器（所有级别，保持颜色）
        logger.add(sys.stdout, level="INFO", colorize=True)
        # 添加文件处理器（只处理WARNING和ERROR级别）
        logger.add(log_file_path, level="ERROR", rotation="10 MB", retention="30 days")
        self.logger = logger.bind(user_id=user_id)

        query_json, save_path = pre_process(mygpt, user_id, question, logger=self.logger) # 得到query_json，并预处理一些体温格式
        start_time = time.time()

        self.logger.info(f"query_json keys: {query_json.keys()}")
        prompt = open(os.path.join(CWD, "prompts", "fill_template_schema.txt"), "r", encoding="utf-8").read()

        # 获取department
        try:
            user_dept = query_json["OperInfo"]["LoginDeptName"]
            # user_dept = user_dept.replace("门诊","").replace("住院部","")
            doctor_name = query_json["PatInfo"]["HouseDocName"]
            # del query_json["OperInfo"]
        except KeyError:
            doctor_name = ""
            user_dept = ""
        self.logger.info(f"【科室】：{user_dept} {doctor_name}")
        current_doc_type = query_json.get("DocType", "")

        # 处理特殊病历
        if "会诊记录-九龙坡" in current_doc_type and user_dept:
            # 处理会诊记录
            consult_request, _ = process_consult_doc(query_json, user_dept)
            if consult_request:
                query_json['CommandInfo'] += f"会诊请求为：{consult_request}"
            if not consult_request:
                query_json['DocType'] = "请会诊"
            # query_json['CommandInfo'] += f"\n请从{user_dept}的角度书写会诊意见。"
        if "入院记录" in current_doc_type and user_dept:
            query_json['CommandInfo'] += f"\n入院记录中「专科情况」仅从{user_dept}的角度书写"
        self.logger.info(f"【用户指令】：{query_json.get('CommandInfo', '')}")

        answer_model_config = self.model_config
        if ("出院记录" in current_doc_type):
            answer_model_config = self.model_config2

        # 设置dic_template，先从预置模板中寻找，没有再从query_json中获取DicTemplate
        # dic_template格式为['2046807:结婚年龄', '2046808:健康状况'...]
        (
            dic_template,
            template_advise,
            dic_template_vk,
            use_preset_template,
            day_limit,
            runtime_schema_fields,
        ) = choose_preset_dic_template(query_json, self.logger)
        del query_json["DocTemplate"]
        del query_json["DicTemplate"]

        # 清理隐私和换行符号
        medical_records = query_json.get("DocInfos", [])
        
        # 清理DocInfos
        if medical_records:
            for item in medical_records:
                item["Content"] = clear_doc_info(item["Content"])
            query_json["DocInfos"] = medical_records
            # clear不必要的Doc
            query_json, current_doc_type = clear_context(query_json, self.logger)
        else:
            current_doc_type = query_json.get("DocType", "")


        

        # 创建JSON schema
        query_json = sort_cut_context(query_json, retain_days=day_limit)
        # open(os.path.join(CWD, "query_save/view_sorted.txt"), "w", encoding="utf-8").write(json.dumps(query_json, ensure_ascii=False, indent=2))
        template_schema = create_schema_from_template(dic_template, use_preset_template, self.logger)
        template_schema = apply_runtime_schema_fields(template_schema, runtime_schema_fields, self.logger)
        prompt = prompt.format(
            DocType=query_json.get("DocType", ""),
            CommandInfo=query_json.get("CommandInfo", ""),
            MedicalRecord=json.dumps(query_json, ensure_ascii=False, indent=2),
            TemplateAdvise=template_advise,
            DicTemplate=template_schema,
            DateTime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        )

        # with open(os.path.join(CWD,"_temp.log"),"w") as f:
        #     f.write(prompt)


        answer = mygpt.chat(
            prompt,  # 提示词
            [],  # 上下文
            answer_model_config,  # 模型配置
            temp_id=user_id,  # 临时ID
            return_think=True,
            json_schema=template_schema,
            json_mode="sglang",
        )
        self.logger.info(f"schema: {template_schema}")
        # try:
        #     print(f"answer:{json.dumps(json.loads(answer), indent=2, ensure_ascii=False)}")
        # except Exception as e:
        #     self.logger.info(f"answer: {answer}. error: {e}")

        self.logger.info(f"answer: {answer}")
        self.logger.info(f"time cost: {time.time() - start_time}s")
        with open(save_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n{answer}")
            f.write(f"\n\n{time.time() - start_time}s")

        if "</think>" in answer:
            self.logger.info(f"think: {answer.split('</think>')[0]}")
            answer = answer.split("</think>")[1]
            answer = answer.strip()

        answer = strip_transient_fields(answer, runtime_schema_fields, self.logger)
        answer = convert_answer_format(answer, dic_template_vk, current_doc_type)

        return question, answer, [], ""
