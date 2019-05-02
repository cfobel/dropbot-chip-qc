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

 - undirected graph <img src="/tex/80a15e0d678bfe0964ebe9db394ab17b.svg?invert_in_darkmode&sanitize=true" align=middle width=80.94040514999999pt height=24.65753399999998pt/>, where:
  * each <img src="/tex/7f8701b1395fa57f1be3d120d1e4eb08.svg?invert_in_darkmode&sanitize=true" align=middle width=40.827471299999985pt height=22.465723500000017pt/> is an electrode id
  * each <img src="/tex/5c87ab8fb304e5929c13eab7158574d7.svg?invert_in_darkmode&sanitize=true" align=middle width=252.4530063pt height=27.945406500000026pt/> is an edge connecting electrodes <img src="/tex/332cc365a4987aacce0ead01b8bdcc0b.svg?invert_in_darkmode&sanitize=true" align=middle width=9.39498779999999pt height=14.15524440000002pt/> and <img src="/tex/deceeaf6940a8c7a5a02373728002b0f.svg?invert_in_darkmode&sanitize=true" align=middle width=8.649225749999989pt height=14.15524440000002pt/>
 - initial **tour**, <img src="/tex/927282af6764b7a5043162e6451c5eae.svg?invert_in_darkmode&sanitize=true" align=middle width=16.15873379999999pt height=31.799054100000024pt/>

perform the following steps:

1. Load starting reservoir <img src="/tex/524934d359267853b5d26e8812f80201.svg?invert_in_darkmode&sanitize=true" align=middle width=37.98526709999999pt height=31.799054100000024pt/>, i.e., first electrode in <img src="/tex/927282af6764b7a5043162e6451c5eae.svg?invert_in_darkmode&sanitize=true" align=middle width=16.15873379999999pt height=31.799054100000024pt/>.
2. Let initial plan <img src="/tex/1de7094e8899e8406bf7b78fdd8767fa.svg?invert_in_darkmode&sanitize=true" align=middle width=79.42923119999999pt height=24.65753399999998pt/>, where <img src="/tex/7997339883ac20f551e7f35efff0a2b9.svg?invert_in_darkmode&sanitize=true" align=middle width=31.99783454999999pt height=24.65753399999998pt/> indicates tour **<img src="/tex/332cc365a4987aacce0ead01b8bdcc0b.svg?invert_in_darkmode&sanitize=true" align=middle width=9.39498779999999pt height=14.15524440000002pt/> expanded**.
3. Let remaining plan <img src="/tex/2683b731e4ee16d99dd61e42cad0a475.svg?invert_in_darkmode&sanitize=true" align=middle width=51.86059724999999pt height=22.465723500000017pt/>.
4. Let <img src="/tex/b95c2b0aab2482e5bebd25332a4bbde0.svg?invert_in_darkmode&sanitize=true" align=middle width=12.30503669999999pt height=14.15524440000002pt/> denote the <img src="/tex/3def24cf259215eefdd43e76525fb473.svg?invert_in_darkmode&sanitize=true" align=middle width=18.32504519999999pt height=27.91243950000002pt/> electrode in <img src="/tex/df5a289587a2f0247a5b97c1e8ac58ca.svg?invert_in_darkmode&sanitize=true" align=middle width=12.83677559999999pt height=22.465723500000017pt/>.
5. While <img src="/tex/f58922a77e58e00d90b6d5cddf0487ba.svg?invert_in_darkmode&sanitize=true" align=middle width=52.106059499999986pt height=24.65753399999998pt/>
 1. Attempt to move liquid from <img src="/tex/add566ef276cab0dc7347620a8377612.svg?invert_in_darkmode&sanitize=true" align=middle width=14.206684799999989pt height=14.15524440000002pt/> to <img src="/tex/8d134381c046e045eaf1f19f41306963.svg?invert_in_darkmode&sanitize=true" align=middle width=14.206684799999989pt height=14.15524440000002pt/> until <img src="/tex/7a4ceff645b3d19c6bd0769baa467fa2.svg?invert_in_darkmode&sanitize=true" align=middle width=109.65580229999999pt height=24.65753399999998pt/>.
 2. If move succeeds, remove <img src="/tex/add566ef276cab0dc7347620a8377612.svg?invert_in_darkmode&sanitize=true" align=middle width=14.206684799999989pt height=14.15524440000002pt/> from the front of <img src="/tex/df5a289587a2f0247a5b97c1e8ac58ca.svg?invert_in_darkmode&sanitize=true" align=middle width=12.83677559999999pt height=22.465723500000017pt/>, i.e., <img src="/tex/56f111f1d9c265b4a21085edd5533ef1.svg?invert_in_darkmode&sanitize=true" align=middle width=76.81481279999998pt height=24.65753399999998pt/>.  Otherwise, remove <img src="/tex/8d134381c046e045eaf1f19f41306963.svg?invert_in_darkmode&sanitize=true" align=middle width=14.206684799999989pt height=14.15524440000002pt/> from <img src="/tex/5201385589993766eea584cd3aa6fa13.svg?invert_in_darkmode&sanitize=true" align=middle width=12.92464304999999pt height=22.465723500000017pt/>, add <img src="/tex/8d134381c046e045eaf1f19f41306963.svg?invert_in_darkmode&sanitize=true" align=middle width=14.206684799999989pt height=14.15524440000002pt/> to <img src="/tex/6030e0f5edbb1383ab4b250382767d99.svg?invert_in_darkmode&sanitize=true" align=middle width=45.02246264999999pt height=22.465723500000017pt/>, and update <img src="/tex/df5a289587a2f0247a5b97c1e8ac58ca.svg?invert_in_darkmode&sanitize=true" align=middle width=12.83677559999999pt height=22.465723500000017pt/> replacing each <img src="/tex/94387c4a1f766b790e518cec2478145d.svg?invert_in_darkmode&sanitize=true" align=middle width=229.84764164999999pt height=24.65753399999998pt/> with <img src="/tex/2887fae492b024fa448fcb7bafd37842.svg?invert_in_darkmode&sanitize=true" align=middle width=71.63830244999998pt height=24.65753399999998pt/>, where <img src="/tex/41fcf5a9f2f993748027cc85f6b2395d.svg?invert_in_darkmode&sanitize=true" align=middle width=44.48447354999999pt height=24.65753399999998pt/> denotes the shortest path between <img src="/tex/44bc9d542a92714cac84e01cbbb7fd61.svg?invert_in_darkmode&sanitize=true" align=middle width=8.68915409999999pt height=14.15524440000002pt/> and <img src="/tex/4bdc8d9bcfb35e1c9bfb51fc69687dfc.svg?invert_in_darkmode&sanitize=true" align=middle width=7.054796099999991pt height=22.831056599999986pt/>.
6. Let <img src="/tex/b95c2b0aab2482e5bebd25332a4bbde0.svg?invert_in_darkmode&sanitize=true" align=middle width=12.30503669999999pt height=14.15524440000002pt/> denote the <img src="/tex/3def24cf259215eefdd43e76525fb473.svg?invert_in_darkmode&sanitize=true" align=middle width=18.32504519999999pt height=27.91243950000002pt/> electrode in <img src="/tex/df5a289587a2f0247a5b97c1e8ac58ca.svg?invert_in_darkmode&sanitize=true" align=middle width=12.83677559999999pt height=22.465723500000017pt/>.
7. Move liquid from <img src="/tex/add566ef276cab0dc7347620a8377612.svg?invert_in_darkmode&sanitize=true" align=middle width=14.206684799999989pt height=14.15524440000002pt/> to <img src="/tex/8d134381c046e045eaf1f19f41306963.svg?invert_in_darkmode&sanitize=true" align=middle width=14.206684799999989pt height=14.15524440000002pt/> until <img src="/tex/da012753bd0cbcaab201c26409bb0c57.svg?invert_in_darkmode&sanitize=true" align=middle width=130.01737814999998pt height=24.65753399999998pt/>; where <img src="/tex/d9324c21b00105263d6f54123813d99c.svg?invert_in_darkmode&sanitize=true" align=middle width=16.45747124999999pt height=14.15524440000002pt/> denotes the expected volume to completely cover <img src="/tex/8d134381c046e045eaf1f19f41306963.svg?invert_in_darkmode&sanitize=true" align=middle width=14.206684799999989pt height=14.15524440000002pt/>.

### Known issues

Currently, **absolute capacitance** is used as an analog for <img src="/tex/e9c9ff78a11a9e77b9c4bae39e056218.svg?invert_in_darkmode&sanitize=true" align=middle width=74.72633519999998pt height=24.65753399999998pt/>.  However, absolute capacitance changes based on the properties of the _dielectric layer_.

This issue may be addressed with the following improvements:

 - **sheet capacitance** (i.e., <img src="/tex/6a6ac3632de852fcc4b13ea5b5187762.svg?invert_in_darkmode&sanitize=true" align=middle width=55.57863464999999pt height=26.76175259999998pt/>) **SHOULD** be calibrated for each chip, for **liquid** and **filler media**, i.e., <img src="/tex/217f97c7d53b63f01d0479a45912f7df.svg?invert_in_darkmode&sanitize=true" align=middle width=20.89050314999999pt height=22.465723500000017pt/> and <img src="/tex/d5d7b8e2020cf6d20bf4babce1f2495e.svg?invert_in_darkmode&sanitize=true" align=middle width=21.97842239999999pt height=22.465723500000017pt/>, respectively.
 - given <img src="/tex/217f97c7d53b63f01d0479a45912f7df.svg?invert_in_darkmode&sanitize=true" align=middle width=20.89050314999999pt height=22.465723500000017pt/>, <img src="/tex/d5d7b8e2020cf6d20bf4babce1f2495e.svg?invert_in_darkmode&sanitize=true" align=middle width=21.97842239999999pt height=22.465723500000017pt/>, an electrode <img src="/tex/b95c2b0aab2482e5bebd25332a4bbde0.svg?invert_in_darkmode&sanitize=true" align=middle width=12.30503669999999pt height=14.15524440000002pt/>, and <img src="/tex/65ed4b231dcf18a70bae40e50d48c9c0.svg?invert_in_darkmode&sanitize=true" align=middle width=13.340053649999989pt height=14.15524440000002pt/>, where <img src="/tex/65ed4b231dcf18a70bae40e50d48c9c0.svg?invert_in_darkmode&sanitize=true" align=middle width=13.340053649999989pt height=14.15524440000002pt/> is the nominal area of <img src="/tex/b95c2b0aab2482e5bebd25332a4bbde0.svg?invert_in_darkmode&sanitize=true" align=middle width=12.30503669999999pt height=14.15524440000002pt/> covered by the reference electrode (i.e., top plate):
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
