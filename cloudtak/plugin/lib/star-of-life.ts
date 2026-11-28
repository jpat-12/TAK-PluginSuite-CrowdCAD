// Star of Life menu icon (tracker R46): Jon's blue star with a white staff and snake, no
// background. Inline SVG rather than an image file, so CloudTAK's CSP never matters and it
// stays crisp. Takes `size` like the @tabler/icons-vue icons CloudTAK's menu normally gets.
import { defineComponent, h } from 'vue';

const BLUE = '#3333BB';
const ARMS = [0, 60, 120];
// One 6.6 × 22 bar per arm, centred on (12, 12) of a 24 × 24 box (tabler's grid).
const bar = (angle: number, extra: Record<string, unknown>) => h('rect', {
    x: 8.7, y: 1, width: 6.6, height: 22, transform: `rotate(${angle} 12 12)`, ...extra,
});

export default defineComponent({
    name: 'IconStarOfLife',
    props: { size: { type: [Number, String], default: 24 } },
    setup(props) {
        return () => h('svg', {
            xmlns: 'http://www.w3.org/2000/svg', viewBox: '0 0 24 24',
            width: props.size, height: props.size, class: 'icon-star-of-life', 'aria-hidden': 'true',
        }, [
            // White outline: stroked bars underneath, then plain bars on top so only the
            // outer edge of the star shows the outline (no lines where the arms cross).
            ...ARMS.map((a) => bar(a, { fill: 'white', stroke: 'white', 'stroke-width': 1.2, 'stroke-linejoin': 'round' })),
            ...ARMS.map((a) => bar(a, { fill: BLUE })),
            // Staff of Asclepius and the snake around it.
            h('line', { x1: 12, y1: 4.2, x2: 12, y2: 20.5, stroke: 'white', 'stroke-width': 1.1, 'stroke-linecap': 'round' }),
            h('path', {
                d: 'M10.6 6.2 C11.4 5 13.6 5.2 13.6 6.4 C13.6 7.8 10.4 8 10.4 9.8 C10.4 11.4 13.6 11.4 13.6 13 '
                 + 'C13.6 14.6 10.4 14.6 10.4 16.2 C10.4 17.4 12 17.6 12.6 17.4',
                fill: 'none', stroke: 'white', 'stroke-width': 0.9, 'stroke-linecap': 'round',
            }),
            h('circle', { cx: 10.5, cy: 6.3, r: 0.75, fill: 'white' }),
        ]);
    },
});
