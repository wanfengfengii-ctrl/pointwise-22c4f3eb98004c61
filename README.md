# 试验波形档案室

试验台交来三个同步采样通道的原始字节与逐条出处。白班资料员验收并封卷，验卷后腾退原录制。接收设备可以要求固定卷更换异或布局。夜班仍凭原卷号领取原序字节，次班质控按卷号和换码请求号核对实读布局、原据与首执。

## 一天的业务流程

1. 试验台送交录制号和三条带出处的波形。资料室按提交顺序固定通道位置，一次接纳整份录制。
2. 白班选择卷号和有序编码表。介质写入三个槽，封卷端重读、校验并反解比对原录制后发布卷号。
3. 夜班领取固定卷，与原录制核对。白班用同源已验卷办理退役，清除目录里的原载荷，然后登记交班。
4. 接收设备送交新的有序编码表。资料室核定可逆性并将请求号绑定到卷号和目标。
5. 每次物理提交更新一个槽。夜班在任一落定暂停点仍可独立领取原波形。
6. 回包丢失后重开，先领取也可，再按原号码和目标办理。三个实读槽都达到目标且通过校验才签首执。
7. 质控员附上请求号登记待办或完成观察。完成观察引用原首执，较早的待办观察仍可核对。
8. 次班可按原参数复领首执并比较当天观察与当前卷。后来换码可改变当前布局，已经记录的历史观察和首执保留原值。

## 运行

需要 Python 3.11 标准库。控制台物化项目时提供标准回归入口。

```sh
python3 -B check_project.py
python3 -B -m demo --root .waveform-demo
```

直接运行同一 unittest 套件可用 `python3 -B -m unittest discover -s tests -t .`。演示位置由 `--root` 指定。可用新的位置从验收开始演示，重复使用同一位置将使用已有样例录制、卷、回执和交班登记。

## Python 接口

通过 `storage.ArchiveStore(root)` 打开或初始化资料室。目录和介质是两个 SQLite 文件，初始化只补建结构，既有录制、槽代次、首执和登记继续使用。下列业务入口各自管理事务。

| 入口 | 输入及输出 |
| --- | --- |
| `recording.ingest.accept_recording` | `store, recording_id, channels`，接纳按原通道位置排列的三个 `recording.channels.ChannelStripe(channel_id, payload, origin)`，返回已接纳录制。 |
| `volume.seal.seal_volume` | `store, recording_id, volume_id, basis`，发布已重读并反解比对的卷。 |
| `recording.retirement.retire_recording` | `store, recording_id, volume_id`，校验同源卷与内容后退役，返回所保留出处。 |
| `recode.requests.submit_recode` | `store, volume_id, request_id, target`，返回待办 `RecodeRequest` 或持久 `RecodeReceipt`。同参复投可继续或复领，`write_limit` 可限制本次实际写入次数。 |
| `pickup.read.read_volume` | `store, volume_id`，返回 `PickupResult`，含原序字节、录制号及逐条出处。`read_with_evidence` 同时返回对应实读视图。 |
| `inspection.shifts.reconcile_shift` | `store, shift_id, volume_id, request_id=None`，返回已登记元数据和本次领取观察。 |

只读查询 `get_request`、`load_first_receipt` 和 `list_shift_entries` 接受 `with store.catalog() as db` 打开的目录连接。前两者分别位于 `recode.requests` 和 `recode.receipts`，登记查询位于 `inspection.register`。`load_first_receipt` 在尚无首执时返回 `None`。`on_boundary` 可观察一次槽写提交前或提交后的事件。回调可在暂停点调用只读入口，抛出 `errors.SlotReplyLost` 可确定性模拟回包丢失。退役和核账入口自己取得目录写事务，应在一次换码调用返回后办理。

## 数据计算及错误

三行按物理槽 0、1、2 排列。行掩码的 1、2、4 位依次代表提交位置 A、B、C，与外部通道名无关。行取 1 到 7，整表须满秩。每个槽逐字节异或对应通道，保留字节长度与原序，无单位换算和舍入。三条明确提供的 `b''` 合法。全零条带仍有编码含义和代次。样例原值 7、11、13，表 `(1,2,5)` 的物理值为 7、11、10，表 `(2,4,3)` 的物理值为 11、13、12。封卷验证、断源领取和核账均使用实际计算结果。

业务错误派生自 `errors.ArchiveError`。非法输入、号码冲突、未知记录、源已退役、介质证据无效及存储失败有独立异常。提交失败的封卷不发布。领取遇到缺槽、坏槽或无效布局会报错。未决换码阻止同卷接纳另一份换码，同号异参也被拒。请求已完成时可以复领历史首执。交班可以只查卷，也可以附属于该卷的请求。持久交班登记保存出处、布局、代次、条带摘要及请求和首执引用，当次返回结果另含实际原始条带。
