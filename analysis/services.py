import datetime
import os
import uuid

import cv2
from flask import current_app
import numpy as np
from PIL import Image, ImageStat, ImageOps

from admin.services import get_group_document
from picture.services import build_picture_path, build_picture_name, find_picture, picture_exists, save_picture_document
from thermal.appmodule import celery

def check_if_image_is_too_dark(filename, brightness_threshold):
    image = Image.open(filename).convert('L')
    stat = ImageStat.Stat(image)
    avg_pixel_value = stat.mean[0]
    if avg_pixel_value < brightness_threshold:
        return True
    return False

@celery.task
def edge_detect_chained(_, img_id_in, alternate_img_id_in, auto_id, wide_id=None, tight_id=None):
    edge_detect(img_id_in, alternate_img_id_in, auto_id, wide_id, tight_id)

@celery.task
def edge_detect_task(img_id_in, alternate_img_id_in, auto_id, wide_id=None, tight_id=None):
    edge_detect(img_id_in, alternate_img_id_in, auto_id, wide_id, tight_id)

def edge_detect(img_id_in, alternate_img_id_in, auto_id, wide_id=None, tight_id=None):
    if picture_exists(alternate_img_id_in):
        img_id_in = alternate_img_id_in
    pic_dict_in = find_picture(img_id_in)
    image_in = cv2.imread(pic_dict_in['uri'])
    gray = cv2.cvtColor(image_in, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    # apply Canny edge detection using a wide threshold, tight
    # threshold, and automatically determined threshold
    auto = auto_canny(blurred)
    auto_filename = build_picture_name(auto_id)
    auto_path_out = build_picture_path(picture_name=auto_filename, snap_id=pic_dict_in['snap_id'])
    cv2.imwrite(auto_path_out, auto)
    auto_dict_out = make_edge_picture_dict(pic_id=auto_id, pic_filename=auto_filename, pic_path=auto_path_out,
                                           snap_id=pic_dict_in['snap_id'], group_id=pic_dict_in['group_id'],
                                           source_pic_id=img_id_in, edge_detect_type='auto')
    save_picture_document(auto_dict_out)
    if wide_id:
        wide = cv2.Canny(blurred, 10, 200)
        wide_filename = build_picture_name(wide_id)
        wide_path_out = build_picture_path(picture_name=wide_filename, snap_id=pic_dict_in['snap_id'])
        cv2.imwrite(wide_path_out, wide)
        wide_dict_out = make_edge_picture_dict(pic_id=wide_id, pic_filename=wide_filename, pic_path=wide_path_out,
                                               snap_id=pic_dict_in['snap_id'], group_id=pic_dict_in['group_id'],
                                               source_pic_id=img_id_in, edge_detect_type='wide')
        save_picture_document(wide_dict_out)
    if tight_id:
        tight = cv2.Canny(blurred, 225, 250)
        tight_filename = build_picture_name(tight_id)
        tight_path_out = build_picture_path(picture_name=tight_filename, snap_id=pic_dict_in['snap_id'])
        cv2.imwrite(tight_path_out, tight)
        tight_dict_out = make_edge_picture_dict(pic_id=tight_id, pic_filename=tight_filename, pic_path=tight_path_out,
                                               snap_id=pic_dict_in['snap_id'], group_id=pic_dict_in['group_id'],
                                               source_pic_id=img_id_in, edge_detect_type='tight')
        save_picture_document(tight_dict_out)

def auto_canny(image, sigma=0.33):
    # compute the median of the single channel pixel intensities
    v = np.median(image)
    # apply automatic Canny edge detection using the computed median
    lower = int(max(0, (1.0 - sigma) * v))
    upper = int(min(255, (1.0 + sigma) * v))
    edged = cv2.Canny(image, lower, upper)
    # return the edged image
    return edged

def make_edge_picture_dict(pic_id, pic_filename, pic_path, snap_id, group_id, source_pic_id, edge_detect_type):
    img_dict_out = {
        '_id': str(pic_id),
        'type': 'picture',
        'source': 'analysis',
        'source_image_id': str(source_pic_id),
        'analysis_type': 'edge detect',
        'edge_detect_type': edge_detect_type,
        'group_id': group_id,
        'snap_id': snap_id,
        'filename': pic_filename,
        'uri': pic_path,
        'created': str(datetime.datetime.now())
    }
    return img_dict_out

@celery.task
def scale_image_chained(_, img_id_in, img_id_out):
    scale_image(img_id_in, img_id_out)

@celery.task
def scale_image_task(img_id_in, img_id_out):
    scale_image(img_id_in, img_id_out)

def scale_image(img_id_in, img_id_out):
# only works on black and white images for now
    group_document = get_group_document('current')
    (colorize_range_low, colorize_range_high) = ('#000080', '#FFD700')
    if 'colorize_range_low' in group_document and 'colorize_range_high' in group_document:
        colorize_range_low = group_document['colorize_range_low']
        colorize_range_high = group_document['colorize_range_high']
    img_dict_in = find_picture(str(img_id_in))
    img_filename_in = img_dict_in['filename']
    img_filename_out = build_picture_name(img_id_out)
    pic_path_in = build_picture_path(picture_name=img_filename_in, snap_id=img_dict_in['snap_id'])
    pic_path_out = build_picture_path(picture_name=img_filename_out, snap_id=img_dict_in['snap_id'])
    image_in = Image.open(pic_path_in)
    image_scaled = image_in.resize(
                        (current_app.config['STILL_IMAGE_WIDTH'], current_app.config['STILL_IMAGE_HEIGHT']),
                        Image.BICUBIC
                   )
    image_colorized = ImageOps.colorize(image_scaled, colorize_range_low, colorize_range_high)
    image_colorized.save(pic_path_out)
    img_dict_out = {
        '_id': str(img_id_out),
        'type': 'picture',
        'source': 'analysis',
        'source_image_id': str(img_id_in),
        'analysis_type': 'scale bicubic',
        'group_id': img_dict_in['group_id'],
        'snap_id': img_dict_in['snap_id'],
        'filename': img_filename_out,
        'uri': pic_path_out,
        'created': str(datetime.datetime.now())
    }
    save_picture_document(img_dict_out)
