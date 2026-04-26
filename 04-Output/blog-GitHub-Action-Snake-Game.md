参考文档：[如何将贪吃蛇游戏添加到您的 Github 页面](https://taozhi.medium.com/how-to-add-a-snake-game-to-your-github-page-d742918fd733)
# 新建仓库

使用您的Github用户名创建一个存储库。 Github 会告诉你

> It is a ✨_special_ ✨ repository that you can use to add a `README.md` to your GitHub profile. Make sure it’s public and initialize it with a README to get started.

表示创建的该存储库，您可以使用它来将`README.md`添加到您的 GitHub 个人资料中。确保它是公共的并使用自述文件对其进行初始化以开始使用
![image.png](https://r2.hecodex.me/obsidian/20241228224238016.png)

在存储库创建的`README.me`中输入一些个人介绍，比如👇：
![image.png](https://r2.hecodex.me/obsidian/20241229002914531.png)

接着打开你个人的Profile页面，你可以直接看见上一步骤中`README.md`中输入的内容，你可以尽可能的丰富你的Profile
![image.png](https://r2.hecodex.me/obsidian/20241229003018994.png)

# 新建Workflow

打开你创建的个人仓库，点击`Actions`选项卡并创建一个新工作流程。单击“新建工作流程”按钮，然后单击`set up workflow yourself`链接
![image.png](https://r2.hecodex.me/obsidian/20241229003239790.png)

这将自动在您的存储库中生成一个名为`.github/workflows`的新文件夹，并在其中生成一个名为`main.yml`
# main.yml
`main.yml` 是 GitHub Actions 的工作流配置文件，用于定义自动化任务的触发条件和执行步骤。

将如下代码复制到你的main.yml 文件中，**无需改动任何地方！**

```yml
name: generate animation

on:
  # run automatically every 24 hours
  schedule:
    - cron: "0 */12 * * *" 
  
  # allows to manually run the job at any time
  workflow_dispatch:
  
  # run on every push on the main branch
  push:
    branches:
    - main

jobs:
  generate:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    
    steps:
      # generates a snake game from a github user (<github_user_name>) contributions graph, output a svg animation at <svg_out_path>
      - name: generate github-contribution-grid-snake.svg
        uses: Platane/snk/svg-only@v3
        with:
          github_user_name: ${{ github.repository_owner }}
          outputs: |
            dist/github-contribution-grid-snake.svg
            dist/github-contribution-grid-snake-dark.svg?palette=github-dark
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          
          
      # push the content of <build_dir> to a branch
      # the content will be available at https://raw.githubusercontent.com/<github_user>/<repository>/<target_branch>/<file> , or as github page
      - name: push github-contribution-grid-snake.svg to the output branch
        uses: crazy-max/ghaction-github-pages@v3.1.0
        with:
          target_branch: output
          build_dir: dist
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }} 
```
## main.yml 详细解释
### 步骤一
- `name`: 工作流的名称，这里是 `generate animation`
- `on`: 定义工作流的触发条件。
    
    - **`schedule`**: 使用 cron 表达式定时触发。`0 */12 * * *` 表示每 12 小时运行一次。
        
    - **`workflow_dispatch`**: 允许在 GitHub 界面上手动触发工作流。
        
    - **`push`**: 当 `main` 分支有推送时触发。
- `jobs`: 定义工作流中的任务。
    
    - **`generate`**: 任务名称。
        
    - **`runs-on`**: 任务运行的环境，这里是 `ubuntu-latest`（最新的 Ubuntu 系统）。
        
    - **`timeout-minutes`**: 任务超时时间，设置为 10 分钟。
- **`uses`**: 使用第三方 Action `Platane/snk/svg-only@v3`，用于生成基于 GitHub 贡献图的蛇形游戏动画。
    
- **`with`**: 传递给 Action 的参数。
    
    - `github_user_name`: GitHub 用户名，这里使用 `${{ github.repository_owner }}` 动态获取仓库所有者。
        
    - `outputs`: 指定输出的 SVG 文件路径。这里生成两个文件：
        
        - `dist/github-contribution-grid-snake.svg`: 默认主题的 SVG 文件。
            
        - `dist/github-contribution-grid-snake-dark.svg?palette=github-dark`: 暗黑主题的 SVG 文件。
            
- **`env`**: 设置环境变量。
    
    - `GITHUB_TOKEN`: 使用 GitHub 提供的 token（`${{ secrets.GITHUB_TOKEN }}`）进行身份验证。

### 步骤二
- **`uses`**: 使用第三方 Action `crazy-max/ghaction-github-pages@v3.1.0`，用于将文件推送到指定分支。
    
- **`with`**: 传递给 Action 的参数。
    
    - `target_branch`: 目标分支，这里是 `output`。
        
    - `build_dir`: 要推送的目录，这里是 `dist`（包含生成的 SVG 文件）。
        
- **`env`**: 设置环境变量。
    
    - `GITHUB_TOKEN`: 使用 GitHub 提供的 token（`${{ secrets.GITHUB_TOKEN }}`）进行身份验证。

# 保存仓库
编辑完成后直接保存在页面上保存本次提交即可

![image.png](https://r2.hecodex.me/obsidian/20241228224336285.png)

# 运行Workflow
保存成功后就会自动运行你的Action了

⚠️但是第一次运行发现居然报错了，点击任务查看具体报错信息，发现是在执行步骤二将生成的svg文件推送到指定分支时没有对应的权限
![image.png](https://r2.hecodex.me/obsidian/20241228225218905.png)

## 开启Actions 权限
在您所创建的存储库下，点击`Settings`，找到`Actions`选项的`General`
![image.png](https://r2.hecodex.me/obsidian/20241228225132802.png)

确保你的`Workflow Permissions`拥有读写权限
![image.png](https://r2.hecodex.me/obsidian/20241228225150862.png)

## 再次运行Workflow
在`Actions`再次Run Workflow，发现本次运行成功
![image.png](https://r2.hecodex.me/obsidian/20241228225320926.png)

# 查看输出
![image.png](https://r2.hecodex.me/obsidian/20241228225343542.png)

# 查看结果
自行替换下述链接中的`{username}`，通过该链接即可访问到生成的动画
https://raw.githubusercontent.com/{username}/{username}/output/github-contribution-grid-snake-dark.svg

![image.png](https://r2.hecodex.me/obsidian/20241228230212473.png)
