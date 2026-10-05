/**
 * 禅道写入前预览的版面。
 * 二次开发只改这个文件的布局。
 * Agent 替换 PREVIEW 后，覆盖写入当前会话的 canvases/zentao-preview.canvas.tsx。
 * 不要把密码、Token 放进 PREVIEW。空数组对应的区块不要显示。
 */
import {
  Callout,
  CollapsibleSection,
  Divider,
  H1,
  H2,
  Row,
  Stack,
  Stat,
  Table,
  Text,
} from "cursor/canvas";

type NewTask = {
  title: string;
  type: string;
  role: string;
  codeVolume: string;
  difficulty: string;
  hours: number;
  assignee: string;
  afterCreate: string;
};

type OwnTask = {
  id: string;
  title: string;
  change: string;
  fromHours: string;
  toHours: string;
};

type OtherTask = {
  id: string;
  title: string;
  openedBy: string;
};

type PreviewData = {
  directWrite: boolean;
  repoMismatch: boolean;
  noRemote: boolean;
  gitRoot: string;
  remote: string;
  product: string;
  project: string;
  story: string;
  execution: string;
  taskSource: string;
  hourRule: string;
  titleRule: string;
  creating: NewTask[];
  updating: OwnTask[];
  readOnly: OtherTask[];
};

const PREVIEW: PreviewData = {
  directWrite: false,
  repoMismatch: false,
  noRemote: false,
  gitRoot: "/path/to/repo",
  remote: "git@example.com:org/repo.git",
  product: "示例产品 (#12)",
  project: "示例项目 (#34)",
  story: "#1012 「支持按日期导出订单」 status=active",
  execution: "#56 「迭代-订单导出」",
  taskSource: "任务从本次锁定仓库的 diff 和这次对话拆出，不改别人已建的任务。",
  hourRule: "工时按代码量和难度，由该任务类型的资深角色估算。",
  titleRule: "标题是动词开头的结果句。",
  creating: [
    {
      title: "实现订单按日期导出 Excel",
      type: "devel",
      role: "资深开发",
      codeVolume: "订单导出模块，约 4 个文件",
      difficulty: "新增导出条件，要改查询和接口",
      hours: 6,
      assignee: "me",
      afterCreate: "标记完成",
    },
  ],
  updating: [],
  readOnly: [],
};

export default function ZentaoPreview() {
  const totalHours = PREVIEW.creating.reduce((sum, task) => sum + task.hours, 0);
  const showTasks = !PREVIEW.repoMismatch;

  return (
    <Stack gap={20}>
      <H1>禅道预览</H1>
      {PREVIEW.directWrite ? (
        <Callout tone="warning" title="配置已关闭确认，将直接写入">
          policy.requirePreview 为 false。下面仍是本次将要写入的内容。
        </Callout>
      ) : null}
      {PREVIEW.repoMismatch ? (
        <Callout tone="danger" title="仓库不一致">
          本次不会写入。请先确认要同步的 git 仓库。
        </Callout>
      ) : null}
      {PREVIEW.noRemote ? (
        <Callout tone="warning" title="无远程">
          确认这条路径之前不会写入。
        </Callout>
      ) : null}
      {showTasks ? (
        <Row gap={16}>
          <Stat value={`${totalHours}h`} label="预计总工时" />
          <Stat value={String(PREVIEW.creating.length)} label="将新建" />
          <Stat value={String(PREVIEW.updating.length)} label="将修改" />
        </Row>
      ) : null}
      <Stack gap={4}>
        <Text>{`仓库：${PREVIEW.gitRoot}`}</Text>
        <Text>{`远程：${PREVIEW.remote || "无远程"}`}</Text>
        <Text>{`产品：${PREVIEW.product}`}</Text>
        <Text>{`项目：${PREVIEW.project}`}</Text>
        <Text>{`需求：${PREVIEW.story}`}</Text>
        <Text>{`迭代：${PREVIEW.execution}`}</Text>
      </Stack>
      <Stack gap={4}>
        <Text tone="secondary">{PREVIEW.taskSource}</Text>
        <Text tone="secondary">{PREVIEW.hourRule}</Text>
        <Text tone="secondary">{PREVIEW.titleRule}</Text>
      </Stack>
      {showTasks && PREVIEW.creating.length > 0 ? (
        <Stack gap={8}>
          <H2>将新建</H2>
          <Table
            headers={["标题", "类型", "角色", "代码量", "难度", "预计", "指派", "完成后"]}
            columnAlign={["left", "left", "left", "left", "left", "right", "left", "left"]}
            rows={PREVIEW.creating.map((task) => [
              task.title,
              task.type,
              task.role,
              task.codeVolume,
              task.difficulty,
              `${task.hours}h`,
              task.assignee,
              task.afterCreate,
            ])}
            striped
          />
        </Stack>
      ) : null}
      {showTasks && PREVIEW.updating.length > 0 ? (
        <Stack gap={8}>
          <H2>将修改</H2>
          <Text tone="secondary" size="small">
            只包括当前账号创建的任务。
          </Text>
          <Table
            headers={["任务", "原标题", "改什么", "工时"]}
            rows={PREVIEW.updating.map((task) => [
              task.id,
              task.title,
              task.change,
              `${task.fromHours} → ${task.toHours}`,
            ])}
            striped
          />
        </Stack>
      ) : null}
      {showTasks && PREVIEW.readOnly.length > 0 ? (
        <CollapsibleSection title="只读，不改" count={PREVIEW.readOnly.length}>
          <Table
            headers={["任务", "标题", "创建人"]}
            rows={PREVIEW.readOnly.map((task) => [task.id, task.title, task.openedBy])}
          />
        </CollapsibleSection>
      ) : null}
      <Divider />
      <Text tone="secondary">请在对话里回复确认或修改意见。确认前不会写入禅道。</Text>
    </Stack>
  );
}
