ALTER TABLE model_configs ADD COLUMN vision_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (vision_enabled IN (0,1));
ALTER TABLE model_configs ADD COLUMN tts_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (tts_enabled IN (0,1));
ALTER TABLE model_configs ADD COLUMN tts_model TEXT NOT NULL DEFAULT '';
ALTER TABLE model_configs ADD COLUMN tts_voice TEXT NOT NULL DEFAULT '';
ALTER TABLE model_configs ADD COLUMN tts_base_url TEXT NOT NULL DEFAULT '';
ALTER TABLE model_configs ADD COLUMN image_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (image_enabled IN (0,1));
ALTER TABLE model_configs ADD COLUMN image_model TEXT NOT NULL DEFAULT '';
ALTER TABLE model_configs ADD COLUMN image_base_url TEXT NOT NULL DEFAULT '';
ALTER TABLE model_configs ADD COLUMN video_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (video_enabled IN (0,1));
ALTER TABLE model_configs ADD COLUMN video_model TEXT NOT NULL DEFAULT '';
ALTER TABLE model_configs ADD COLUMN video_base_url TEXT NOT NULL DEFAULT '';

UPDATE model_configs
SET model_type='multimodal', vision_enabled=1,
    tts_enabled=1, tts_model='speech-2.8-hd', tts_voice='male-qn-qingse',
    tts_base_url=CASE WHEN TRIM(tts_base_url)='' THEN base_url ELSE tts_base_url END,
    image_enabled=1, image_model='image-01',
    image_base_url=CASE WHEN TRIM(image_base_url)='' THEN base_url ELSE image_base_url END
WHERE lower(provider) LIKE '%minimax%' OR lower(model_name) LIKE '%minimax%';

UPDATE multimodal_tasks
SET prompt='图片生成任务 #' || id
WHERE TRIM(prompt)<>'' AND length(replace(replace(prompt,'?',''),' ',''))=0;
