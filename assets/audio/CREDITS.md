# 音频素材来源与授权

本目录只收录 **CC0（公共领域）** 素材：可商用、可修改、无需署名。
下面把这些信息记全，一是出于尊重，二是以后换素材时能一眼看出"哪些是我加的、
哪些原本就在"。

## 背景音乐 `music/`

| 文件 | 曲名 | 作者 | 来源 | 授权 |
|---|---|---|---|---|
| `bgm_game.ogg` | Keep your dream alive! (seamless loop) | congusbongus | <https://opengameart.org/content/keep-your-dream-alive-seamless-loop> | CC0 1.0 |
| `bgm_menu.ogg` | Upbeat Chiptune Theme | nihilocrat | <https://opengameart.org/content/upbeat-chiptune-theme> | CC0 1.0 |

两首都是 8-bit / chiptune 风格的循环曲，跟火柴人这条线的轻喜剧调性一致。
`bgm_game.ogg` 是作者专门做的无缝循环（73.4 秒），`bgm_menu.ogg` 原本是
一个 Pyweek 参赛作品的菜单曲（56.9 秒）。

格式说明：都是 ogg vorbis。海龟环境（pygame 1.9.6 + SDL_mixer）实测能流式
播放；选 ogg 而不是 wav，是因为同样的时长 wav 要 3MB 以上、ogg 只要 1.2MB。

## 其余音效 `footsteps/` `impacts/` `items/` `ui/` `music/jingles_*`

这些是项目脚手架自带的素材（命名风格与目录结构对应 Kenney 的资源包，
Kenney 全系为 CC0）。**当前代码没有使用它们**：音效一律由 `audio.py`
在运行时合成，理由见该文件开头——合成音效没有"文件丢失 / 没打包"
这一类"没声音"的故障。

它们保留在仓库里是为了将来替换：想换成真实录音，把 `audio.py` 的
`_SYNTH` 表改成从这些路径加载即可，接口不用动。
