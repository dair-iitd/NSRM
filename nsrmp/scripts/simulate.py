import os
import argparse
import time
import torch
import numpy as np

import sys
sys.path.append("/home/vishal/projects/nsrmp")

from PIL import Image
import pybullet as p
import pybullet_data as pd

from panda.settings import camera_settings
from panda.dsl import DSL
from panda.panda import PandaPrimitive, PandaState

from PIL import Image
import cv2
import numpy as np
import os
import json
import shutil

from data_generation import construct, get_scenes_json, get_instructions_json, configs
from datasets.roboclevr.definition import build_nsrm_dataset
from model.configs import configs as model_configs 
from model.model_new import Model
from helpers.mytorch.cuda.copy import async_copy_to
from data_generation.panda.construct.base import ConstructBase
from scripts.pixel_to_world import load_model
from helpers.mytorch.vision.ops.boxes import box_convert
from helpers.utils.type_conversion import str2bool

# Example list
# awesome tower of 3: /home/vishal/projects/nsrmp/data_new/train/00012, /home/vishal/projects/nsrmp/data_new/test/00297/
# tower of 3 failing coz too off prediction: /home/namas/Desktop/nsrmp/data/test/00413
# on top (not good): /home/vishal/projects/nsrmp/data_new/test/00041
# 5 step: /home/vishal/projects/nsrmp/data_general/multi-step/test/00014
# weird on top: /home/vishal/projects/nsrmp/data_new/val/03940, /home/vishal/projects/nsrmp/data_new/test/00041
# weird pick-place: /home/vishal/projects/nsrmp/data_generation/tmp_train-0/0005, /home/vishal/projects/nsrmp/data_generation/tmp_train-0/0001
# 15 blocks, on side: /home/vishal/projects/nsrmp/data_generation/tmp_train-0/0004
# weird top, 15 blocks: /home/vishal/projects/nsrmp/data_generation/tmp_train-0/0007
# stack test, first good: /home/vishal/projects/nsrmp/data_new/test/00015, train: /home/vishal/projects/nsrmp/data_new/train/01338, 

parser = argparse.ArgumentParser()
parser.add_argument('--record', type=str2bool, default = True)
parser.add_argument('--video_filename', type=str, default = '/home/vishal/projects/nsrmp/nsrmp/recorded.mp4')
parser.add_argument('--width', default=1024, help='Width of GUI Window')
parser.add_argument('--height', default=768, help='Height of GUI Window')

# parser.add_argument('--model_path', default="/home/himanshu/Desktop/nsrmp/model_saves/model_explicit_action_concept_2step_new.pth")
# parser.add_argument('--model_path', default="/home/himanshu/Desktop/nsrmp/model_saves/splitter_relational_2.pth")
# parser.add_argument('--model_path', default="/home/namas/Desktop/nsrmp/final_models/model_single_step_relational.pth")
parser.add_argument('--model_path', default="/home/namas/Desktop/nsrmp/model_saves/model_final_single_step_relational.pth")

parser.add_argument('--example_path', default='/home/vishal/projects/nsrmp/data_new/test/00823')
parser.add_argument('--predicted', type=str2bool, default = True)
parser.add_argument('--adjust_horizontal', default = True)

parser.add_argument('--datadir', type = str, default = '../data/')
parser.add_argument('--vocab_json', default='/home/namas/Desktop/nsrmp/data/vocab.json')
parser.add_argument('--training_target', default = 'splitter')
parser.add_argument('--use_cuda', type=bool, default = True)
parser.add_argument('--instruction_transform', type = str, default = 'basic')
parser.add_argument('--batch_size', default = True)
parser.add_argument('--use_gt_grasp', default = False)
args = parser.parse_args()

if os.path.exists(os.path.join(args.datadir, 'sample')):
	shutil.rmtree(os.path.join(args.datadir, 'sample'))
os.makedirs(os.path.join(args.datadir, 'sample'))

new_example_path = os.path.join(args.datadir, 'sample', os.path.basename(os.path.normpath(args.example_path)))
shutil.copytree(args.example_path, new_example_path)

config = {
	'demo_json_path': os.path.join(new_example_path, 'demo.json')
}

movements = []

if args.predicted:
	get_scenes_json.main(os.path.join(args.datadir, 'sample'), 'sample', 'scenes-sample.json', out_dir=args.datadir)
	get_instructions_json.main(os.path.join(args.datadir, 'sample'), 'sample', 'instructions-sample.json', args.datadir)

	sample_dataset = build_nsrm_dataset(args, model_configs, os.path.join(args.datadir, 'sample'), os.path.join(args.datadir, 'scenes-sample.json'), os.path.join(args.datadir, 'instructions-sample.json'), args.vocab_json)

	model = Model(sample_dataset.vocab, model_configs ,training_target = args.training_target)
	model.prepare_model('usual')

	if args.use_cuda:
		model.cuda()

	# model.load_state_dict(torch.load(args.model_path))
	from helpers.mytorch.base.serialization import load_state_dict
	load_state_dict(model, args.model_path, partial = True, modules = ['parser','resnet','visual','action_sim','concept_embeddings'])
	load_state_dict(model,'/home/himanshu/Desktop/nsrmp/model_saves/splitter_relational_2.pth', partial = True, modules = ['multi_step_builder'])
	model.eval()

	kwargs = dict(unique_mode = 'argmax', gumbel_tau = 0.00001)

	dataloader = sample_dataset.make_dataloader(1, shuffle = False, sampler = None, drop_last = True)
	for batch in dataloader:
		if args.use_cuda:
			batch = async_copy_to(batch,dev=0, main_stream=None)
		outputs = model(batch, **kwargs)

	pixel2world_model = load_model()
	if args.use_cuda:
		pixel2world_model.cuda()

	for (bbox_orig, move_obj_mask, bbox) in outputs['movements'][0]:
		nonzeros = torch.nonzero(move_obj_mask)
		assert len(nonzeros) == 1, "Only one object can be moved!"
		move_obj_idx = nonzeros[0][0]

		bbox = box_convert(bbox, model_configs.data.bbox_mode, 'xywh')

		bbox_orig = box_convert(bbox_orig, model_configs.data.bbox_mode, 'xywh')

		target_pos = pixel2world_model(bbox)
		initial_pos = pixel2world_model(bbox_orig)
		print(move_obj_idx, bbox, target_pos)
		print(bbox[1]*args.width, bbox[0]*args.height, bbox[3]*args.width, bbox[2]*args.height)
		movements.append((move_obj_idx, list(target_pos), list(initial_pos)))

else:
	# Ideal movement
	with open(config['demo_json_path'], 'r') as f:
		demo_data = json.load(f)
		for i,prog in enumerate(demo_data['grounded_program']):
			move_obj_idx = prog[1]
			target_pos = demo_data['object_positions'][i+1][move_obj_idx] # For ith program, check pos at i+1th frame
			print(target_pos)
			movements.append((move_obj_idx, target_pos, None))

timeStep = 1/240.0
if args.record:
	video_filename = '/home/vishal/Desktop/videos/'+os.path.basename(os.path.normpath(args.example_path))+'-ours.mp4'
	assert not os.path.exists(video_filename)
	construct.init_bulletclient(timeStep, args.width, args.height, video_filename)
else:
	construct.init_bulletclient(timeStep)


constructBase = ConstructBase(p, [0,0,0], config, args.height, args.width, None, set_hide_panda_body=False)

for move_obj_idx, target_pos, initial_pos in movements:
	if args.use_gt_grasp:
		initial_pos = None
	constructBase.move_object(move_obj_idx, target_pos, use_panda=True, initial_pos=initial_pos, adjust_horizontal=args.adjust_horizontal)



# View matrix, projection matrix doesn't seem to work

#   view_matrix  = p.getDebugVisualizerCamera()[2]
#   proj_matrix  = p.getDebugVisualizerCamera()[3]

#   proj_matrix = np.asarray(proj_matrix).reshape([4, 4], order="F")
#   view_matrix = np.asarray(view_matrix).reshape([4, 4], order="F")
#   tran_pix_world = np.linalg.inv(np.matmul(proj_matrix, view_matrix))

#   print(tran_pix_world)

#   bbox = [
#     0.27734375,
#     0.30859375,
#     0.061197916666666664,
#     0.0595703125,
#     0.8274509803921568
#   ]
#   point = np.matmul(tran_pix_world, np.array([bbox[0], -1*bbox[1], 2*bbox[4]-1, 1]).T).T
#   point /= point[3]
#   point = point[:3]

#   print(list(point))

#   tran_3d_world = np.matmul(proj_matrix, view_matrix)
  
#   point = [
#       0.26917704379755997,
#       -0.08166219149317759,
#       0.67,
#       1
#   ]

#   point = np.matmul(tran_3d_world, np.array(point).T).T
#   point /= point[3]
#   point = point[:3]

#   print(list(point))
