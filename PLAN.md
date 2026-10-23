# План: свой «AnimEasy на минималках» (один аддон)

Пользователь (аниматор, пишет по-русски) хочет один аддон: Motion Trail Editor (этот репозиторий) +
нужные ему функции в духе AnimEasy. AnimEasy платный — код не копировать, реализовать заново.
Рабочее имя аддона не выбрано — спросить при старте (пока пакет `motion_trail_editor`).

## Что нужно (ответы пользователя)

1. **Селектор (главное).** Сохранить текущее выделение костей как кнопку-группу и потом одним кликом
   выделять ровно эти кости (пример: все контроллеры губ; Alt+G / выделение коллекции цепляет лишние
   контроллеры из той же bone collection). Как в AnimEasy «Selection Buttons»: кнопки с цветом,
   клик — выделить (Shift — добавить, Ctrl — убрать), переименовать, перекрасить, порядок, удалить.
   Для объектов в Object Mode — так же. **Пользователь пришлёт скрины, как это выглядит в AnimEasy — дождаться.**
2. **Кнопки в шапке Dope Sheet / Timeline**, как в AnimEasy (там всё в header: `panels.py` AnimEasy).
3. **Tween / Breakdowner** — поза между соседними ключами (blend to neighbor / ease / push-pull).
4. **Очистка: только Euler Filter.**
5. **Отображение:** Ghosts (onion skin), Silhouette (переключение вьюпорта в силуэт), AnimOffset
   (правка позы на текущем кадре переносится на всю анимацию / диапазон).
6. **Motion Trail Editor** — уже готов (v0.3.2), войти в этот же аддон.
7. Не нужно: copy/paste позы, зеркальный выбор, сброс трансформов, IK/FK, inbetween +/−, интерполяция, прочая чистка.

## Где смотреть, как это сделано в AnimEasy (только для понимания UX)

`C:\Users\user\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\animEasy\` (v1.0.6, пропатчен под 5.2):
- `operators/operators.py`: SaveGroup ~2837, SelectGroup ~2899, EditGroupName ~2979, RemoveGroup ~3014,
  SetIcon ~3030, MoveGroupUp/Down ~3047/3063, меню цвета ~3080, `AEASY_PT_SelectionPopover` ~3093;
  breakdowner/neighbor/easer/pusher ~828–1110; AnimOffset ~1630 (+ `utils.global_offset_from_user`);
  Ghosts ~1763; Silhouette ~2236; Euler filter ~1452.
- `panels/panels.py`: отрисовка кнопок в шапках (флаги `prefs["show_..."]`), иконки в `icons/`.

## Что уже выяснено (технически)

- Пользователь: Blender 5.2.2 (основной, к нему подключён Blender MCP) и 4.3.2. Аддон должен работать в обоих.
  Совместимость: `trails.SLOTTED_ACTIONS` (слоты action с 4.4), `trails.POSE_BONE_SELECT`
  (`PoseBone.select` с 5.0, раньше `Bone.select`) + `select_bone()/bone_selected()`; в 4.3 нет шейдера
  `POINT_FLAT_COLOR` (фолбэк `FLAT_COLOR`). `Window.modal_operators` есть в обеих.
- По умолчанию F-кривые со сглаживанием Continuous Acceleration — правка ключа меняет auto-ручки всей кривой.
- Установка у пользователя: extension `%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default\motion_trail_editor`
  (ставить zip через `bpy.ops.extensions.package_install_files` в его Blender через MCP). Две копии
  одновременно нельзя — в `register()` есть проверка.
- Сборка: `python dev/package.py` → `dist/*.zip` (extension + legacy). Версия в `__init__.py` и манифесте должна совпадать.
- Тесты: `dev/test_core.py` (фон), `dev/test_gui.py` (окно + `--enable-event-simulate`; события клавиш
  обязательно с x,y; заставку выключить; выход через `os._exit`, иначе перезапишется quit.blend).
  Запускать в 4.3 и 5.2. `dev/test_install.py` — установка в изолированный профиль (`BLENDER_USER_RESOURCES`).
- Песочница команд ломает junction/симлинки — создавать их через процесс Blender (MCP).
- Видео-тутор: `dev/tutorial/record.py` (+ `encode.py`), запись в развёрнутом окне, реальный темп.
- Тяжёлая сцена пользователя: `E:\Beku\Work\GreekGods\Locations\underwater.blend` (846 объектов, Rigify-риги).
  Всё тяжёлое — только по изменениям, не во время G/R/S и проигрывания (`trails.blender_busy()`).

## Порядок работы

1. ~~Селектор~~ — готов в 0.4.0 (`selections.py`, `Scene.anim_selection_sets`, попап в шапке таймлайна,
   кнопки в tool header вьюпорта; тест `t_selection_sets`; скрины `dev/shot_selections.py`). Установлен у пользователя.
2. ~~Кнопки в шапке~~ — 0.5.0: `header.py` (+ AddonPreferences: какие группы, Graph Editor).
3. ~~Tween / Breakdowner, Euler Filter~~ — `keytools.py` (Tween / Neighbor / Push-Pull, drag-модал, свой Euler filter).
4. ~~Ghosts, Silhouette, AnimOffset~~ — `ghosts.py`, `silhouette.py`, `offset.py`; общие хелперы в `common.py`.
5. Тесты: core 24/24, GUI 28/28, `dev/test_tools_gui.py` 6/6 в 4.3 и 5.2. README обновлён.
   Осталось: пользователь ставит 0.5.0 сам (MCP подключён к его рабочему underwater — туда не лезть);
   обновить тутор; возможно переименовать аддон (id `motion_trail_editor` не менять — иначе две копии).
