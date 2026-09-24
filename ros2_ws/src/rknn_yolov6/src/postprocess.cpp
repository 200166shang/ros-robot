#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include <sys/time.h>
#include <vector>
#include "rknn_yolov6/postprocess.hpp"
#include <stdint.h>


inline static int clamp(float val, int min, int max)
{
    return val > min ? (val < max ? val : max) : min;//小于等于0，则等于0；大于等于max,则等于max
}

static float CalculateOverlap(float xmin0, float ymin0, float xmax0, float ymax0, float xmin1, float ymin1, float xmax1, float ymax1)
{
    float w = fmax(0.f, fmin(xmax0, xmax1) - fmax(xmin0, xmin1) + 1.0);
    float h = fmax(0.f, fmin(ymax0, ymax1) - fmax(ymin0, ymin1) + 1.0);
    float i = w * h;
    float u = (xmax0 - xmin0 + 1.0) * (ymax0 - ymin0 + 1.0) + (xmax1 - xmin1 + 1.0) * (ymax1 - ymin1 + 1.0) - i;
    return u <= 0.f ? 0.f : (i / u);
}

static int nms(int validCount, std::vector<float> &outputLocations, std::vector<int> &order, float threshold)
{
    for (int i = 0; i < validCount; ++i)
    {
        if (order[i] == -1)
        {
            continue;
        }
        int n = order[i];
        for (int j = i + 1; j < validCount; ++j)
        {
            int m = order[j];
            if (m == -1)
            {
                continue;
            }
            float xmin0 = outputLocations[n * 4 + 0];
            float ymin0 = outputLocations[n * 4 + 1];
            float xmax0 = outputLocations[n * 4 + 0] + outputLocations[n * 4 + 2];
            float ymax0 = outputLocations[n * 4 + 1] + outputLocations[n * 4 + 3];

            float xmin1 = outputLocations[m * 4 + 0];
            float ymin1 = outputLocations[m * 4 + 1];
            float xmax1 = outputLocations[m * 4 + 0] + outputLocations[m * 4 + 2];
            float ymax1 = outputLocations[m * 4 + 1] + outputLocations[m * 4 + 3];

            float iou = CalculateOverlap(xmin0, ymin0, xmax0, ymax0, xmin1, ymin1, xmax1, ymax1);

            if (iou > threshold)
            {
                order[j] = -1;
            }
        }
    }
    return 0;
}

static int quick_sort_indice_inverse(
    std::vector<float> &input,
    int left,
    int right,
    std::vector<int> &indices)
{
    float key;
    int key_index;
    int low = left;
    int high = right;
    if (left < right)
    {
        key_index = indices[left];
        key = input[left];
        while (low < high)
        {
            while (low < high && input[high] <= key)
            {
                high--;
            }
            input[low] = input[high];
            indices[low] = indices[high];
            while (low < high && input[low] >= key)
            {
                low++;
            }
            input[high] = input[low];
            indices[high] = indices[low];
        }
        input[low] = key;
        indices[low] = key_index;
        quick_sort_indice_inverse(input, left, low - 1, indices);
        quick_sort_indice_inverse(input, low + 1, right, indices);
    }
    return low;
}

static float sigmoid(float x)
{
    return 1.0 / (1.0 + expf(-x));
}

static float unsigmoid(float y)
{
    return -1.0 * logf((1.0 / y) - 1.0);
}

inline static int32_t __clip(float val, float min, float max)
{
    float f = val <= min ? min : (val >= max ? max : val);
    return f;
}

static int8_t qnt_f32_to_affine(float f32, int32_t zp, float scale)
{
    float dst_val = (f32 / scale) + zp;
    //int8_t res = (int8_t)__clip(dst_val, 0, 255);

    int8_t res     = (int8_t)__clip(dst_val, -128, 127);
    return res;
}

static float deqnt_affine_to_f32(int8_t qnt, int32_t zp, float scale)
{
    return ((float)qnt - (float)zp) * scale;
}

static int process(int8_t* input,  int grid_h, int grid_w, int height, int width, int stride,
                   std::vector<float>& boxes, std::vector<float>& objProbs, std::vector<int>& classId, float threshold,
                   int32_t zp, float scale,int OBJ_CLASS_NUM)
{
  int    validCount = 0;
//   int    grid_len   = grid_h * grid_w;
//   float  thres      = unsigmoid(threshold);
//   int8_t thres_i8   = qnt_f32_to_affine(thres, zp, scale);
//   for (int a = 0; a < 3; a++) {
//     for (int i = 0; i < grid_h; i++) {
//       for (int j = 0; j < grid_w; j++) {
//         int8_t box_confidence = input[((5+OBJ_CLASS_NUM) * a + 4) * grid_len + i * grid_w + j];
//         if (box_confidence >= thres_i8) {
//           int     offset = ((5+OBJ_CLASS_NUM) * a) * grid_len + i * grid_w + j;
//           int8_t* in_ptr = input + offset;
//           float   box_x  = sigmoid(deqnt_affine_to_f32(*in_ptr, zp, scale)) * 2.0 - 0.5;
//           float   box_y  = sigmoid(deqnt_affine_to_f32(in_ptr[grid_len], zp, scale)) * 2.0 - 0.5;
//           float   box_w  = sigmoid(deqnt_affine_to_f32(in_ptr[2 * grid_len], zp, scale)) * 2.0;
//           float   box_h  = sigmoid(deqnt_affine_to_f32(in_ptr[3 * grid_len], zp, scale)) * 2.0;
//           box_x          = (box_x + j) * (float)stride;
//           box_y          = (box_y + i) * (float)stride;
//           box_w          = box_w * box_w * (float)anchor[a * 2];
//           box_h          = box_h * box_h * (float)anchor[a * 2 + 1];
//           box_x -= (box_w / 2.0);
//           box_y -= (box_h / 2.0);

//           int8_t maxClassProbs = in_ptr[5 * grid_len];
//           int    maxClassId    = 0;
//           for (int k = 1; k < OBJ_CLASS_NUM; ++k) {
//             int8_t prob = in_ptr[(5 + k) * grid_len];
//             if (prob > maxClassProbs) {
//               maxClassId    = k;
//               maxClassProbs = prob;
//             }
//           }
//           if (maxClassProbs>= thres_i8){
//             objProbs.push_back(sigmoid(deqnt_affine_to_f32(maxClassProbs, zp, scale))
//                                * sigmoid(deqnt_affine_to_f32(box_confidence, zp, scale)));
//             classId.push_back(maxClassId);
//             validCount++;
//             boxes.push_back(box_x);
//             boxes.push_back(box_y);
//             boxes.push_back(box_w);
//             boxes.push_back(box_h);
//           }
//         }
//       }
//     }
//   }
  return validCount;
}


static int process_float(float *input,  int grid_h, int grid_w, int height, int width, int stride,
                   std::vector<float> &boxes, std::vector<float> &objProbs, std::vector<int> &classId,
                   float threshold, int32_t zp, float scale,int OBJ_CLASS_NUM)
{
    int validCount = 0;
    int grid_len = grid_h * grid_w;

    //printf("hxw %dx%d %dx%d %d\n",grid_h,grid_w,height,width,stride);

    for (int i = 0; i < grid_h; i++)
    {
        for (int j = 0; j < grid_w; j++)
        {
            if( input[4 * grid_len + i*grid_w + j] < threshold )//4+1+80
            {
               continue;
            }//这一步可以节约大量后处理时间，并且减少CPU占用，但是要将ReduMax在模型推理中完成，模型推理也调用的是CPU，所以CPU会在推理时偏高

            //4+1+80 or 4+80

            float *in_ptr = input + i*grid_w + j;

            //float prob_max = in_ptr[4 * grid_len];
            float prob_max = in_ptr[5 * grid_len];
            int maxClassId = 0;
            for (int c = 1; c < OBJ_CLASS_NUM; c++)
            {
                 //float prob = in_ptr[(4 + c) * grid_len];
                 float prob = in_ptr[(5 + c) * grid_len];
                 if (prob > prob_max)
                 {
                     maxClassId = c;
                     prob_max = prob;
                 }
            }

            if (prob_max >= threshold)
            {

                float box_x =  j + 0.5 - in_ptr[0 * grid_len];
                float box_y =  i + 0.5 - in_ptr[1 * grid_len];
                float box_x2 = j + 0.5 + in_ptr[2 * grid_len];
                float box_y2 = i + 0.5 + in_ptr[3 * grid_len];

                float box_w = box_x2-box_x;
                float box_h = box_y2-box_y;

                //printf("prob=%f\n",maxClassProbs);
                // objProbs.push_back(maxClassProbs);
                // classId.push_back(maxClassId);

                objProbs.push_back(prob_max);
                classId.push_back(maxClassId);

                boxes.push_back(box_x*stride);
                boxes.push_back(box_y*stride);
                boxes.push_back(box_w*stride);
                boxes.push_back(box_h*stride);

                validCount++;
            }
        }
    }

    return validCount;
}

int post_process(uint8_t want_float,void *input0, void *input1, void *input2, int model_in_h, int model_in_w,
                 float conf_threshold, float nms_threshold, float scale_w, float scale_h,
                 std::vector<int32_t> &qnt_zps, std::vector<float> &qnt_scales,std::vector<int> &out_index,
                 std::vector<std::string> &label_names,int cls_num,
                 std::vector<Det> &dets)
{

    std::vector<float> filterBoxes;
    std::vector<float> boxesScore;
    std::vector<int> classId;
    int stride0 = 8;
    int grid_h0 = model_in_h / stride0;
    int grid_w0 = model_in_w / stride0;
    int validCount0 = 0;

    int stride1 = 16;
    int grid_h1 = model_in_h / stride1;
    int grid_w1 = model_in_w / stride1;
    int validCount1 = 0;

    int stride2 = 32;
    int grid_h2 = model_in_h / stride2;
    int grid_w2 = model_in_w / stride2;
    int validCount2 = 0;


    if(want_float)
    {
        validCount0 = process_float((float *)input0,  grid_h0, grid_w0, model_in_h, model_in_w,
                              stride0, filterBoxes, boxesScore, classId, conf_threshold, qnt_zps[out_index[0]], qnt_scales[out_index[0]],cls_num);//注意此处索引可能从2开始！！！

        validCount1 = process_float((float *)input1,  grid_h1, grid_w1, model_in_h, model_in_w,
                              stride1, filterBoxes, boxesScore, classId, conf_threshold, qnt_zps[out_index[1]], qnt_scales[out_index[1]],cls_num);

        validCount2 = process_float((float *)input2,  grid_h2, grid_w2, model_in_h, model_in_w,
                              stride2, filterBoxes, boxesScore, classId, conf_threshold, qnt_zps[out_index[2]], qnt_scales[out_index[2]],cls_num);
    }
    else
    {
        validCount0 = process((int8_t *)input0,  grid_h0, grid_w0, model_in_h, model_in_w,
                              stride0, filterBoxes, boxesScore, classId, conf_threshold, qnt_zps[out_index[0]], qnt_scales[out_index[0]],cls_num);//注意此处索引可能从2开始！！！

        validCount1 = process((int8_t *)input1,  grid_h1, grid_w1, model_in_h, model_in_w,
                              stride1, filterBoxes, boxesScore, classId, conf_threshold, qnt_zps[out_index[1]], qnt_scales[out_index[1]],cls_num);

        validCount2 = process((int8_t *)input2,  grid_h2, grid_w2, model_in_h, model_in_w,
                              stride2, filterBoxes, boxesScore, classId, conf_threshold, qnt_zps[out_index[2]], qnt_scales[out_index[2]],cls_num);
    }

    int validCount = validCount0 + validCount1 + validCount2;
    if (validCount <= 0)
    {
        return 0;
    }

    std::vector<int> indexArray;
    for (int i = 0; i < validCount; ++i)
    {
        indexArray.push_back(i);
    }

    quick_sort_indice_inverse(boxesScore, 0, validCount - 1, indexArray);

    nms(validCount, filterBoxes, indexArray, nms_threshold);

    for (int i = 0; i < validCount; ++i)
    {
        if (indexArray[i] == -1 || boxesScore[i] < conf_threshold || i >= 100)
        {
            continue;
        }

        int n = indexArray[i];

        float x1 = filterBoxes[n * 4 + 0];
        float y1 = filterBoxes[n * 4 + 1];
        float x2 = x1 + filterBoxes[n * 4 + 2];
        float y2 = y1 + filterBoxes[n * 4 + 3];
        int id = classId[n];

        Det det;
        det.x1 = (int)(clamp(x1, 0, model_in_w-1) * scale_w);
        det.y1 = (int)(clamp(y1, 0, model_in_h-1) * scale_h);
        det.x2 = (int)(clamp(x2, 0, model_in_w-1) * scale_w);
        det.y2 = (int)(clamp(y2, 0, model_in_h-1) * scale_h);
        det.conf = boxesScore[n];
        det.cls_name = label_names[id];
        det.cls_id = id;
        det.obj_id = 0;
        dets.push_back(det);
    }

    return 0;
}
