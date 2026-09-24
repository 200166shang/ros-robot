#ifndef _RKNN_ZERO_COPY_DEMO_POSTPROCESS_H_
#define _RKNN_ZERO_COPY_DEMO_POSTPROCESS_H_

#include <stdint.h>
#include <vector>
#include <string>

typedef struct
{
    unsigned short x1;
    unsigned short y1;
    unsigned short x2;
    unsigned short y2;
    float conf;
    std::string cls_name;
    unsigned short cls_id;
    unsigned short obj_id;
}Det;

int post_process(uint8_t want_float,void *input0, void *input1, void *input2, int model_in_h, int model_in_w,
                 float conf_threshold, float nms_threshold, float scale_w, float scale_h,
                 std::vector<int32_t> &qnt_zps, std::vector<float> &qnt_scales,std::vector<int> &out_index,
                 std::vector<std::string> &label_names,int cls_num,
                 std::vector<Det> &dets);

#endif //_RKNN_ZERO_COPY_DEMO_POSTPROCESS_H_
