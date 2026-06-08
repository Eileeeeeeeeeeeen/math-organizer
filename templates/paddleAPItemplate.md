🔬 PaddleOCR-VL 完整 API 格式参考
一、安装
Bash
# 基本安装（包含文档解析能力）
pip install -U "paddleocr[doc-parser]"
# NVIDIA GPU（CUDA 12.6 为例）
python -m pip install paddlepaddle-gpu==3.2.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
# x64 CPU
python -m pip install paddlepaddle==3.2.1 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
版本要求：Python 3.9–3.13

二、Python SDK API
2.1 导入 & 基本用法
Python
from paddleocr import PaddleOCRVL
# 默认使用 GPU 0，否则 CPU；Pipeline 版本默认 v1.6
pipeline = PaddleOCRVL()
# 单文件处理
output = pipeline.predict("image.png")
for res in output:
    res.print()                        # 打印结构化结果
    res.save_to_markdown("./output")   # 保存为 Markdown
    res.save_to_json("./output")       # 保存为 JSON
    res.save_to_word("./output")       # 保存为 Word
2.2 PaddleOCRVL() 构造参数全表
参数	类型	默认值	说明
pipeline_version	str	"v1.6"	Pipeline 版本："v1" / "v1.5" / "v1.6"
device	str|None	None	推理设备：cpu / gpu:0 / xpu:0 / npu:0 / dcu:0 / metax_gpu:0 等
engine	str|None	None	推理引擎：None(相当于paddle) / paddle / paddle_static / paddle_dynamic / transformers
engine_config	dict|None	None	推理引擎配置（与 engine 配合使用）
布局分析			
use_layout_detection	bool|None	None（→ True）	是否启用布局分析模块
layout_detection_model_name	str|None	None	布局分析模型名称
layout_detection_model_dir	str|None	None	布局分析模型本地目录
layout_threshold	float|dict|None	None	布局检测置信度阈值（0-1）或按类别设置
layout_nms	bool|None	None	是否启用 NMS 后处理
layout_unclip_ratio	float|Tuple[float,float]|dict|None	None	检测框扩展系数
layout_merge_bboxes_mode	str|dict|None	None	检测框合并模式：large / small / union
layout_shape_mode	str	"auto"	几何表示模式：rect / quad / poly / auto
merge_layout_blocks	bool|None	None（→ True）	是否合并跨栏检测框
VLM 识别			
vl_rec_model_name	str|None	None	VLM 模型名称
vl_rec_model_dir	str|None	None	VLM 模型本地目录
vl_rec_backend	str|None	None	VLM 推理后端：vllm-server / sglang-server / fastdeploy-server / mlx-vlm-server / llama-cpp-server
vl_rec_server_url	str|None	None	VLM 服务地址
vl_rec_api_model_name	str|None	None	VLM 服务模型名称
vl_rec_api_key	str|None	None	VLM 服务 API Key
vl_rec_max_concurrency	int|None	None	VLM 最大并发请求数
文档预处理			
use_doc_orientation_classify	bool|None	None（→ False）	是否启用文档方向分类
doc_orientation_classify_model_name	str|None	None	方向分类模型名称
doc_orientation_classify_model_dir	str|None	None	方向分类模型目录
use_doc_unwarping	bool|None	None（→ False）	是否启用文档扭曲校正
doc_unwarping_model_name	str|None	None	扭曲校正模型名称
doc_unwarping_model_dir	str|None	None	扭曲校正模型目录
功能开关			
use_chart_recognition	bool|None	None（→ False）	是否启用图表识别
use_seal_recognition	bool|None	None（→ False）	是否启用印章识别
use_ocr_for_image_block	bool|None	None（→ False）	是否对图像块内文字进行 OCR
format_block_content	bool|None	None（→ False）	是否将 block_content 格式化为 Markdown
use_queues	bool|None	None（→ True）	是否启用内部队列异步处理
Markdown 输出			
markdown_ignore_labels	list|None	None	在 Markdown 中忽略的布局标签（默认忽略 number/footnote/header/header_image/footer/footer_image/aside_text）
高性能推理			
enable_hpi	bool	None	是否启用高性能推理
use_tensorrt	bool	False	是否启用 TensorRT
precision	str	"fp32"	计算精度："fp32" / "fp16"
enable_mkldnn	bool	True	是否启用 MKL-DNN
mkldnn_cache_capacity	int	10	MKL-DNN 缓存容量
cpu_threads	int	10	CPU 推理线程数
paddlex_config	str	None	PaddleX 流水线配置文件路径
2.3 predict() / predict_iter() 方法参数
Python
output = pipeline.predict(
    input,                          # 必传：图片路径/URL/目录/numpy.ndarray/list
    use_doc_orientation_classify=None,
    use_doc_unwarping=None,
    use_layout_detection=None,
    use_chart_recognition=None,
    use_seal_recognition=None,
    use_ocr_for_image_block=None,
    layout_threshold=None,
    layout_nms=None,
    layout_unclip_ratio=None,
    layout_merge_bboxes_mode=None,
    layout_shape_mode="auto",
    use_queues=None,
    prompt_label=None,              # 仅在 use_layout_detection=False 时生效
    format_block_content=None,
    merge_layout_blocks=None,
    markdown_ignore_labels=None,
    repetition_penalty=None,        # VLM 重复惩罚
    temperature=None,               # VLM 采样温度
    top_p=None,                     # VLM top-p 采样
    min_pixels=None,               # VLM 图像最小像素
    max_pixels=None,               # VLM 图像最大像素
    max_new_tokens=None,           # VLM 最大生成 token 数
    vlm_extra_args=None,           # VLM 额外配置（如各类型 min/max pixels）
)
input 参数支持类型：

str：本地图片/PDF 路径、URL、本地目录
numpy.ndarray：图像数据
list：上述类型的列表
vlm_extra_args 支持的键：

键	说明
ocr_min_pixels / ocr_max_pixels	OCR 分辨率范围
table_min_pixels / table_max_pixels	表格分辨率范围
chart_min_pixels / chart_max_pixels	图表分辨率范围
formula_min_pixels / formula_max_pixels	公式分辨率范围
seal_min_pixels / seal_max_pixels	印章分辨率范围
2.4 restructure_pages() 方法
Python
output = pipeline.restructure_pages(
    res_list,               # list|None - 多页 PDF 预测结果列表
    merge_tables=True,      # Bool - 是否跨页合并表格
    relevel_titles=True,    # Bool - 是否解析多级标题
    concatenate_pages=False # Bool - 是否合并多页为单页
)
2.5 Result 对象方法全表
方法	参数	类型	默认值	说明
print()	format_json	bool	True	是否格式化 JSON 缩进输出
indent	int	4	缩进级别
ensure_ascii	bool	False	是否转义非ASCII字符
save_to_json()	save_path	str	None	保存路径（目录或文件）
indent	int	4	JSON 缩进级别
ensure_ascii	bool	False	是否转义非ASCII字符
save_to_markdown()	save_path	str	None	保存路径
pretty	bool	True	是否美化输出
show_formula_number	bool	False	是否保留公式编号
save_to_img()	save_path	str	None	保存可视化图像
save_to_html()	save_path	str	None	表格保存为 HTML
save_to_xlsx()	save_path	str	None	表格保存为 Excel
save_to_word()	save_path	str	None	保存为 Word (.docx)
2.6 Result 对象属性
属性	类型	说明
json	dict	获取预测结果的 dict 格式
img	dict	获取可视化图像（键：layout_det_res / overall_ocr_res / text_paragraphs_ocr_res / formula_res_region1 / table_cell_img / seal_res_region1）
markdown	dict	获取 Markdown 结果（键：markdown_texts / markdown_images / page_continuation_flags）
三、CLI 命令格式
3.1 基本用法
Bash
# GPU（默认）
paddleocr doc_parser -i <图片/PDF路径/URL> --save_path ./output
# 其他硬件
paddleocr doc_parser -i <input> --device cpu       # CPU
paddleocr doc_parser -i <input> --device xpu       # 昆仑芯
paddleocr doc_parser -i <input> --device dcu       # 海光DCU
paddleocr doc_parser -i <input> --device metax_gpu # MetaX
# 引擎切换
paddleocr doc_parser -i <input> --engine transformers
# 启用文档预处理
paddleocr doc_parser -i <input> --use_doc_orientation_classify True --use_doc_unwarping True
# 禁用布局检测（纯 VLM 模式）
paddleocr doc_parser -i <input> --use_layout_detection False
3.2 连接 VLM 推理服务
Bash
# 本地 vLLM 服务
paddleocr doc_parser -i <input> \
  --vl_rec_backend vllm-server \
  --vl_rec_server_url http://localhost:8118/v1
# 硅基流动 (SiliconFlow) 平台
paddleocr doc_parser -i <input> \
  --pipeline_version v1.5 \
  --vl_rec_backend vllm-server \
  --vl_rec_server_url https://api.siliconflow.cn/v1 \
  --vl_rec_api_model_name 'PaddlePaddle/PaddleOCR-VL-1.5' \
  --vl_rec_api_key xxxxxx
3.3 CLI 参数速查表
CLI 参数	类型	默认值	说明
-i / --input	str	必传	输入图片/PDF路径/URL/目录
--save_path	str	—	结果保存路径
--pipeline_version	str	"v1.6"	版本：v1 / v1.5 / v1.6
--device	str	—	设备：cpu / gpu:0 / xpu / dcu / metax_gpu
--engine	str|None	None	引擎：paddle / paddle_static / paddle_dynamic / transformers
--layout_detection_model_name	str	—	布局模型名
--layout_detection_model_dir	str	—	布局模型目录
--layout_threshold	float	—	布局阈值 0-1
--layout_nms	bool	—	是否使用 NMS
--layout_unclip_ratio	float	—	扩展系数 >0
--layout_merge_bboxes_mode	str	—	large / small / union
--layout_shape_mode	str	"auto"	rect / quad / poly / auto
--vl_rec_model_name	str	—	VLM 模型名
--vl_rec_model_dir	str	—	VLM 模型目录
--vl_rec_backend	str	—	VLM 后端
--vl_rec_server_url	str	—	VLM 服务地址
--vl_rec_max_concurrency	int	—	最大并发
--vl_rec_api_model_name	str	—	VLM 服务模型名
--vl_rec_api_key	str	—	VLM 服务 API Key
--doc_orientation_classify_model_name	str	—	方向分类模型名
--doc_orientation_classify_model_dir	str	—	方向分类模型目录
--doc_unwarping_model_name	str	—	扭曲校正模型名
--doc_unwarping_model_dir	str	—	扭曲校正模型目录
--use_doc_orientation_classify	bool	—	启用方向分类
--use_doc_unwarping	bool	—	启用扭曲校正
--use_layout_detection	bool	—	启用布局分析
--use_chart_recognition	bool	—	启用图表识别
--use_seal_recognition	bool	—	启用印章识别
--use_ocr_for_image_block	bool	—	OCR 图像块内文字
--format_block_content	bool	—	格式化 block_content
--merge_layout_blocks	bool	—	合并跨栏检测框
--markdown_ignore_labels	str	—	Markdown 忽略标签
--use_queues	bool	—	启用内部队列
--prompt_label	str	—	VLM prompt 类型
--repetition_penalty	float	—	重复惩罚
--temperature	float	—	采样温度
--top_p	float	—	top-p 采样
--min_pixels	int	—	最小像素
--max_pixels	int	—	最大像素
--enable_hpi	bool	None	高性能推理
--use_tensorrt	bool	False	TensorRT 加速
--precision	str	fp32	精度
--enable_mkldnn	bool	True	MKL-DNN
--mkldnn_cache_capacity	int	10	MKL-DNN 缓存
--cpu_threads	int	10	CPU 线程数
--paddlex_config	str	—	PaddleX 配置文件路径
四、REST API（Service Deployment）
4.1 端点概览
端点	方法	说明
/layout-parsing	POST	执行布局解析
/restructure-pages	POST	多页结果重组（跨页表格合并、标题层级重建、多页拼接）
4.2 /layout-parsing 请求体
Json
{
  "file": "<Base64编码文件内容 或 文件URL>",
  "fileType": 1,
  "useDocOrientationClassify": null,
  "useDocUnwarping": null,
  "useLayoutDetection": null,
  "useChartRecognition": null,
  "useSealRecognition": null,
  "useOcrForImageBlock": null,
  "layoutThreshold": null,
  "layoutNms": null,
  "layoutUnclipRatio": null,
  "layoutMergeBboxesMode": null,
  "layoutShapeMode": "auto",
  "promptLabel": null,
  "formatBlockContent": null,
  "repetitionPenalty": null,
  "temperature": null,
  "topP": null,
  "minPixels": null,
  "maxPixels": null,
  "maxNewTokens": null,
  "mergeLayoutBlocks": null,
  "markdownIgnoreLabels": null,
  "vlmExtraArgs": null,
  "prettifyMarkdown": true,
  "showFormulaNumber": false,
  "restructurePages": false,
  "mergeTables": true,
  "relevelTitles": true,
  "returnMarkdownImages": true,
  "outputFormats": null,
  "visualize": null
}
参数说明（仅列出与前文不同的）：

参数	类型	必填	说明
file	string	✅ 是	Base64编码的文件内容 或 文件 URL
fileType	integer|null	否	0=PDF, 1=图片(含TIFF)；不传则从URL推断
restructurePages	boolean	否	是否跨页重组（默认 false）
mergeTables	boolean	否	仅当 restructurePages=true 生效
relevelTitles	boolean	否	仅当 restructurePages=true 生效
returnMarkdownImages	boolean	否	是否返回 Markdown 中的图片（默认 true）
outputFormats	array|null	否	额外导出格式，目前仅支持 ["docx"]
prettifyMarkdown	boolean	否	是否美化 Markdown（默认 true）
showFormulaNumber	boolean	否	是否保留公式编号（默认 false）
visualize	boolean|null	否	是否返回可视化图像
4.3 /layout-parsing 成功响应
Json
{
  "logId": "<UUID>",
  "errorCode": 0,
  "errorMsg": "Success",
  "result": {
    "layoutParsingResults": [
      {
        "prunedResult": { /* 预测结果字典 */ },
        "markdown": {
          "text": "<Markdown 文本>",
          "images": { "relative/path.png": "<Base64 或 URL>" }
        },
        "outputImages": {
          "layout_det_res": "<Base64 或 URL>",
          "overall_ocr_res": "<Base64 或 URL>",
          "...": "..."
        },
        "inputImage": "<Base64 或 URL>",
        "exports": {
          "docx": { "content": "<Base64 或 URL>" }
        }
      }
    ],
    "dataInfo": {}
  }
}
4.4 /restructure-pages 请求体
Json
{
  "pages": [
    {
      "prunedResult": { /* 来自 infer 的 prunedResult */ },
      "markdownImages": { /* 来自 infer 的 markdown.images */ }
    }
  ],
  "mergeTables": true,
  "relevelTitles": true,
  "concatenatePages": false,
  "prettifyMarkdown": true,
  "showFormulaNumber": false,
  "returnMarkdownImages": true,
  "outputFormats": null
}
4.5 服务部署命令速查
Bash
# Docker Compose 一键部署（推荐）
docker compose up   # 在 compose.yaml 所在目录执行，端口 8080
# 手动部署
paddlex --install serving
paddlex --serve --pipeline PaddleOCR-VL              # PaddlePaddle 引擎
paddlex --serve --pipeline PaddleOCR-VL --engine transformers  # Transformers 引擎
paddlex --serve --pipeline PaddleOCR-VL --port 8111  # 自定义端口
4.6 VLM 推理服务启动
Bash
# Docker 镜像（vLLM）
docker run -it --rm --gpus all --network host \
  ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-genai-vllm-server:latest-nvidia-gpu \
  paddleocr genai_server --model_name PaddleOCR-VL-1.6-0.9B --host 0.0.0.0 --port 8118 --backend vllm
# CLI 安装并启动
paddleocr install_genai_server_deps vllm
paddleocr genai_server --model_name PaddleOCR-VL-1.6-0.9B --backend vllm --port 8118
五、多语言客户端调用示例
官方提供了 Python / C++ / Java / Go / C# / Node.js / PHP 的完整 HTTP 调用示例，核心流程：

Text
1. POST /layout-parsing → 获取 prunedResult + markdown.images
2. POST /restructure-pages → 获取重组后的结构化结果
3. 将 Markdown 文本 + 图片写入本地文件
来源确认：以上所有 API 参数和格式均来自 PaddleOCR 官方文档站，对应版本 PaddleOCR v3.6.0 / PaddleOCR-VL-1.6。

⚠️ 重要提示：请确保使用完整 Pipeline（PaddleOCRVL 类或 paddleocr doc_parser 命令），而非仅调用裸 VLM 模型，否则将无法获得文档中的 SOTA 准确率（96.3%）。
