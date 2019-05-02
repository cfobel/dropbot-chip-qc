# dropbot-chip-qc #

Quality control tools for testing DropBot digital microfluidic chips.

<!-- vim-markdown-toc GFM -->

* [Test routine](#test-routine)
    * [Terminology](#terminology)
    * [Algorithm (pseudocode)](#algorithm-pseudocode)
        * [Known issues](#known-issues)
* [Install](#install)
* [License](#license)
* [Contributors](#contributors)

<!-- vim-markdown-toc -->

-------------------------------------------------------------------------------

# Test routine

## Terminology

 - **Tour:** list of electrode ids to visit in order (**MAY** include duplicate ids)
 - **Expanded tour:** a **tour** where the shortest path between each pair of
   adjacent ids (i.e., $e_i$ and $e_{i+1}$) is $(e_i, e_{i+1})$.

## Algorithm (pseudocode)

Given:

 - undirected graph $G = (E, C)$, where:
  * each $e \in E$ is an electrode id
  * each $c \in C \subseteq \left\{\left{x, y\right} \mathrel{}\middle|\mathrel{} (x, y) \in E^2 \wedge x \neq y\right}$ is an edge connecting electrodes $x$ and $y$
 - initial **tour**, $\vec{T}_0$

perform the following steps:

1. Load starting reservoir $\vec{T}_0(0)$, i.e., first electrode in $\vec{T}_0$.
2. Let initial plan $P_0 = f(T_0)$, where $f(x)$ indicates tour **$x$ expanded**.
3. Let remaining plan $P = P_0$.
4. Let $e_i$ denote the $i^{th}$ electrode in $P$.
5. While $|P| \geq 3$
 1. Attempt to move liquid from $e_1$ to $e_2$ until $volume(e_3) > \epsilon$.
 2. If move succeeds, remove $e_1$ from the front of $P$, i.e., $P = P\left[1:\right]$.  Otherwise, remove $e_2$ from $G$, add $e_2$ to $G_{error}$, and update $P$ replacing each $\left\{(e_i, e_{i+1}, e_{i+2}) \in P \mathrel{}\middle|\mathrel{} e_{i+1} = e_2 \right\}$ with $y(e_i, e_{i+1})$, where $y(a, b)$ denotes the shortest path between $a$ and $b$.
6. Let $e_i$ denote the $i^{th}$ electrode in $P$.
7. Move liquid from $e_1$ to $e_2$ until $volume(e_2) > \alpha \mu_2$; where $\mu_2$ denotes the expected volume to completely cover $e_2$.

### Known issues

Currently, **absolute capacitance** is used as an analog for $volume(a)$.  However, absolute capacitance changes based on the properties of the _dielectric layer_.

This issue may be addressed with the following improvements:

 - **sheet capacitance** (i.e., $F/mm^2$) **SHOULD** be calibrated for each chip, for **liquid** and **filler media**, i.e., $\Omega_L$ and $\Omega_F$, respectively.
 - given $\Omega_L$, $\Omega_F$, an electrode $e_i$, and $a_i$, where $a_i$ is the nominal area of $e_i$ covered by the reference electrode (i.e., top plate):
   * the **minimal overlap threshold** **SHOULD** be calculated as $\epsilon_i = a_i \Omega_F + a_\epsilon \Omega_L$.
   * the **expected overlap threshold** **SHOULD** be calculated as $\mu_i = a_i \left(\Omega_F + \alpha \Omega_L\right)$.

-------------------------------------------------------------------------------

# Install

The latest [`dropbot-chip-qc` release][1] is available as a
[Conda][2] package from the [`sci-bots`][2] channel.

To install `dropbot-chip-qc` in an **activated Conda environment**, run:

    conda install -c sci-bots -c conda-forge dropbot-chip-qc

-------------------------------------------------------------------------------

# License

This project is licensed under the terms of the [BSD license](/LICENSE.md)

-------------------------------------------------------------------------------

# Contributors

 - Christian Fobel ([@sci-bots](https://github.com/sci-bots))


[1]: https://github.com/sci-bots/dropbot-chip-qc
[2]: https://anaconda.org/sci-bots/dropbot-chip-qc
